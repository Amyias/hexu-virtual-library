"""Build only the pixel sun and moon, verify other assets unchanged, then export and render them.

    blender --background --factory-startup --python-exit-code 1 --python blender/build_celestial.py

Pass `-- --out <dir>` to write the GLB, previews, blend and manifest into a scratch copy first.
"""
import bpy
import sys
import json
import hashlib
from pathlib import Path
from mathutils import Vector
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'blender'))
from celestial import create_sun, create_moon, GRID, PIXEL, DEPTH, SUN_COLORS, MOON_COLORS
PROTECTED = ['blender/hexu-library.blend', 'public/models/hexu-library.glb', 'public/models/xiaohe-pet.glb',
             'public/models/smart-book.glb', 'public/models/shelf-book.glb', 'public/models/book-inventory.json',
             'public/models/lighting-rig.json']
args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = Path(args[args.index('--out') + 1]).resolve() if '--out' in args else ROOT


def snapshot():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PROTECTED if (ROOT / name).exists()}


def stats(root):
    meshes = [obj for obj in root.children_recursive if obj.type == 'MESH']
    for obj in meshes:
        obj.data.calc_loop_triangles()
    points = [obj.matrix_world @ Vector(v) for obj in meshes for v in obj.bound_box]
    size = [max(v[i] for v in points) - min(v[i] for v in points) for i in range(3)]
    return {'meshes': [obj.name for obj in meshes],
            'pixels': sum(obj['pixels'] for obj in meshes),
            'triangles': sum(len(obj.data.loop_triangles) for obj in meshes),
            'width_m': round(size[0], 4), 'height_m': round(size[2], 4), 'depth_m': round(size[1], 4)}


before = snapshot()
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
sun, moon = create_sun(), create_moon()
bpy.context.view_layer.update()
summary = {'PixelSun': stats(sun), 'PixelMoon': stats(moon)}
for name, info in summary.items():
    assert len(info['meshes']) == 2, info
    assert info['triangles'] < 3000, info
    assert abs(info['depth_m'] - DEPTH) < 1e-5, info
    assert info['width_m'] <= GRID * PIXEL + 1e-5 and info['height_m'] <= GRID * PIXEL + 1e-5, info
# The sun is symmetric: rays reach every edge of the grid.
assert abs(summary['PixelSun']['width_m'] - GRID * PIXEL) < 1e-5
assert abs(summary['PixelSun']['height_m'] - GRID * PIXEL) < 1e-5

(OUT / 'public/models').mkdir(parents=True, exist_ok=True)
(OUT / 'blender').mkdir(parents=True, exist_ok=True)
glb = OUT / 'public/models/celestial.glb'
bpy.ops.object.select_all(action='DESELECT')
for root in (sun, moon):
    root.select_set(True)
    for obj in root.children_recursive:
        obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(glb), export_format='GLB', use_selection=True, export_yup=True,
                          export_extras=True, export_animations=False, export_cameras=False, export_lights=False)

# Studio stays in the editable blend but is never exported to the browser asset.
scene.render.engine = 'CYCLES'; scene.cycles.samples = 16; scene.cycles.use_denoising = True
scene.render.resolution_x = 640; scene.render.resolution_y = 640; scene.render.resolution_percentage = 100
scene.view_settings.view_transform = 'Standard'
camera_data = bpy.data.cameras.new('CelestialCamera'); camera_data.type = 'ORTHO'; camera_data.ortho_scale = GRID * PIXEL * 1.15
camera = bpy.data.objects.new('CelestialCamera', camera_data); scene.collection.objects.link(camera); scene.camera = camera
camera.location = (0, -4, 0); camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
for shown, hidden, world in [(sun, moon, (.62, .7, .78)), (moon, sun, (.07, .09, .16))]:
    # The backdrop is seen by the camera only; the emissive pixels keep their palette values.
    scene.world.use_nodes = True
    nodes, links = scene.world.node_tree.nodes, scene.world.node_tree.links
    nodes['Background'].inputs['Color'].default_value = (*world, 1)
    if 'Camera only' not in nodes:
        path, mix = nodes.new('ShaderNodeLightPath'), nodes.new('ShaderNodeMixShader')
        mix.name = 'Camera only'
        links.new(path.outputs['Is Camera Ray'], mix.inputs['Fac'])
        links.new(nodes['Background'].outputs['Background'], mix.inputs[2])
        links.new(mix.outputs['Shader'], nodes['World Output'].inputs['Surface'])
    for obj in [hidden, *hidden.children_recursive]:
        obj.hide_render = True
    for obj in [shown, *shown.children_recursive]:
        obj.hide_render = False
    scene.render.filepath = str(OUT / 'blender' / ('celestial-' + shown.name[5:].lower() + '.png'))
    bpy.ops.render.render(write_still=True)
for obj in [moon, *moon.children_recursive]:
    obj.hide_render = False

assert snapshot() == before, 'An unrelated library/model asset changed'
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'blender/celestial.blend'))
manifest = {'grid': GRID, 'pixel_m': PIXEL, 'depth_m': DEPTH, 'bodies': summary,
            'palettes': {'sun': SUN_COLORS, 'moon': MOON_COLORS},
            'protected_assets': before, 'glb_bytes': glb.stat().st_size}
(OUT / 'blender/celestial-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
print('CELESTIAL_VERIFIED ' + json.dumps(manifest), flush=True)
