"""Editable pixel sun and crescent moon. Input dimensions use Three.js X/Y-up/Z-forward metres.

Both bodies are one-voxel-thick pixel grids: every lit cell becomes a cube, but only faces that
border an empty cell are emitted, so the silhouette stays crisp and the mesh stays light.
The art faces Three.js +Z (Blender -Y); the browser yaws it toward the camera.
"""
import math
import bmesh
import bpy

GRID = 22
PIXEL = 0.08
DEPTH = 0.08
CENTER = GRID / 2

# Palettes follow the usual 2-3 tone pixel convention: base, lower-right shadow, upper-left
# highlight; no black outline. Values are sRGB hex.
SUN_COLORS = {'core': 'F7C53B', 'shade': 'E9962F', 'light': 'FFE89A', 'ray': 'F2AE36'}
MOON_COLORS = {'face': 'F1E8C6', 'shade': 'D4C597', 'crater': 'C2B286', 'star': 'FFF4CF'}


def _offsets(i, j):
    """Cell centre relative to the grid centre; j grows upward."""
    return i + .5 - CENTER, j + .5 - CENTER


def sun_cells():
    """Return {(i, j): tone}. Disc radius 6.3 cells; four 3-cell cardinal rays and four 2x2 diagonal
    rays, each one cell clear of the disc so they read as short chunky rays."""
    cells = {}
    for i in range(GRID):
        for j in range(GRID):
            x, y = _offsets(i, j)
            d = math.hypot(x, y)
            if d <= 6.3:
                light = -x * .7 + y * .7  # toward the upper-left
                if d > 5.1 and light < 1.5:
                    cells[(i, j)] = 'shade'
                elif light > 3.2 and d > 2.4:
                    cells[(i, j)] = 'light'
                else:
                    cells[(i, j)] = 'core'
            elif (abs(x) < 1 and 7.5 <= abs(y) <= 10.5) or (abs(y) < 1 and 7.5 <= abs(x) <= 10.5):
                cells[(i, j)] = 'ray'
            elif abs(x) in (5.5, 6.5) and abs(y) in (5.5, 6.5):
                cells[(i, j)] = 'ray'
    return cells


def moon_cells():
    """Crescent from two overlapping circles (radius 7, cut by radius 6 offset up-right)."""
    cells = {}
    for i in range(GRID):
        for j in range(GRID):
            x, y = _offsets(i, j)
            if math.hypot(x, y) > 7.1 or math.hypot(x - 4, y - 2.5) <= 6.1:
                continue
            inner = math.hypot(x - 4, y - 2.5)
            cells[(i, j)] = 'shade' if inner <= 7.1 else 'face'
    for crater in [(-4.5, -1.5), (-3.5, -4.5), (-5.5, 1.5), (-2.5, -5.5)]:
        key = (int(crater[0] + CENTER - .5), int(crater[1] + CENTER - .5))
        if key in cells:
            cells[key] = 'crater'
    return cells


def star_cells():
    """Three pixel sparkles in the crescent's open side: one plus-shaped, two single pixels."""
    cells = {}
    for x, y in [(6.5, 7.5), (7.5, 6.5), (6.5, 6.5), (5.5, 6.5), (6.5, 5.5), (9.5, 0.5), (3.5, 9.5)]:
        cells[(int(x + CENTER - .5), int(y + CENTER - .5))] = 'star'
    return cells


def material(name, hex_color):
    rgb = [int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4)]
    rgba = tuple(((v+.055)/1.055)**2.4 if v > .04045 else v/12.92 for v in rgb) + (1,)
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.use_nodes = True
    node = mat.node_tree.nodes.get('Principled BSDF')
    node.inputs['Base Color'].default_value = rgba
    node.inputs['Roughness'].default_value = 1
    node.inputs['Emission Color'].default_value = rgba
    node.inputs['Emission Strength'].default_value = 1
    return mat


def voxel_mesh(name, cells, palette, parent):
    """Build one mesh from a pixel grid with one material slot per tone actually used."""
    tones = sorted(set(cells.values()))
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    for tone in tones:
        mesh.materials.append(material(f'{name} {tone} | {palette[tone]}', palette[tone]))
    bm = bmesh.new()
    verts = {}

    def vert(x, y, z):
        key = (round(x, 6), round(y, 6), round(z, 6))
        if key not in verts:
            verts[key] = bm.verts.new(key)
        return verts[key]

    half = DEPTH / 2
    for (i, j), tone in cells.items():
        x0, x1 = (i - CENTER) * PIXEL, (i + 1 - CENTER) * PIXEL
        z0, z1 = (j - CENTER) * PIXEL, (j + 1 - CENTER) * PIXEL  # Blender Z is up
        quads = [((x0, -half, z0), (x1, -half, z0), (x1, -half, z1), (x0, -half, z1)),  # front
                 ((x1, half, z0), (x0, half, z0), (x0, half, z1), (x1, half, z1))]  # back
        if (i - 1, j) not in cells:
            quads.append(((x0, half, z0), (x0, -half, z0), (x0, -half, z1), (x0, half, z1)))
        if (i + 1, j) not in cells:
            quads.append(((x1, -half, z0), (x1, half, z0), (x1, half, z1), (x1, -half, z1)))
        if (i, j - 1) not in cells:
            quads.append(((x0, half, z0), (x1, half, z0), (x1, -half, z0), (x0, -half, z0)))
        if (i, j + 1) not in cells:
            quads.append(((x0, -half, z1), (x1, -half, z1), (x1, half, z1), (x0, half, z1)))
        for quad in quads:
            face = bm.faces.new([vert(*v) for v in quad])
            face.material_index = tones.index(tone)
    bm.to_mesh(mesh)
    bm.free()
    for polygon in mesh.polygons:
        polygon.use_smooth = False
    obj['pixels'] = len(cells)
    return obj


def empty(name, location=(0, 0, 0)):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.empty_display_size = .3
    return obj


def create_sun():
    root = empty('PixelSun')
    root['source'] = 'Blender procedural pixel grid'
    root['grid'] = GRID
    root['pixel_m'] = PIXEL
    cells = sun_cells()
    disc = {k: v for k, v in cells.items() if v != 'ray'}
    rays = {k: v for k, v in cells.items() if v == 'ray'}
    voxel_mesh('PixelSunDisc', disc, SUN_COLORS, root)
    voxel_mesh('PixelSunRays', rays, SUN_COLORS, root)
    return root


def create_moon():
    root = empty('PixelMoon')
    root['source'] = 'Blender procedural pixel grid'
    root['grid'] = GRID
    root['pixel_m'] = PIXEL
    voxel_mesh('PixelMoonFace', moon_cells(), MOON_COLORS, root)
    voxel_mesh('PixelMoonStars', star_cells(), MOON_COLORS, root)
    return root
