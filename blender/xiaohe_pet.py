"""Editable pixel companion model. Input dimensions use Three.js X/Y-up/Z-forward metres."""
import bpy

PIXEL = 0.78 / 43
BODY_COLOR = 'D87656'


def pos(v):
    return (v[0], -v[2], v[1])


def material(name, hex_color, roughness):
    rgb = [int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4)]
    rgba = tuple(((v+.055)/1.055)**2.4 if v > .04045 else v/12.92 for v in rgb) + (1,)
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.use_nodes = True
    node = mat.node_tree.nodes.get('Principled BSDF')
    node.inputs['Base Color'].default_value = rgba
    node.inputs['Roughness'].default_value = roughness
    node.inputs['Metallic'].default_value = 0
    return mat


def empty(name, location, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    obj.location = pos(location)
    obj.empty_display_size = .04
    return obj


def box(name, location, size, mat, parent, bevel=.003):
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.object
    obj.name = name
    obj.parent = parent
    obj.location = pos(location)
    obj.dimensions = (size[0], size[2], size[1])
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if bevel:
        modifier = obj.modifiers.new('Pixel edge bevel', 'BEVEL')
        modifier.width = bevel
        modifier.segments = 1
        modifier.affect = 'EDGES'
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        # Flat faces preserve the silhouette rather than turning this into a rounded toy.
    return obj


def create_pet():
    """Front silhouette follows the supplied 63x53 reference, measured on its orange pixel runs."""
    root = empty('XiaoHePet', (0, 0, 0))
    orange = material('Pet terracotta | D87656', BODY_COLOR, .76)
    eyes = material('Pet black eyes', '171918', .9)
    # Pixel edges: x=8..50, body x=15..43, y=21..41; feet y=42..49.
    root['source'] = 'Blender procedural model, user-provided reference'
    root['reference_color'] = '#' + BODY_COLOR
    root['reference_pixels'] = 'body 29x21; silhouette 43x29; four short legs'
    root['width_m'] = .78
    root['height_m'] = 29 * PIXEL
    root['depth_m'] = .26
    body = box('PetBody', (0, 4 * PIXEL, 0), (29 * PIXEL, 21 * PIXEL, .26), orange, root, .004)
    for name, x in [('PetEyeLeft', -9 * PIXEL), ('PetEyeRight', 9 * PIXEL)]:
        box(name, (x, 5.5 * PIXEL, .133), (5 * PIXEL, 4 * PIXEL, .008), eyes, body, .0007)
    for name, sign in [('PetArmLeft', -1), ('PetArmRight', 1)]:
        pivot = empty(name, (sign * 14.5 * PIXEL, 4 * PIXEL, 0), root)
        box(name + 'Mesh', (sign * 3.5 * PIXEL, 0, 0), (7 * PIXEL, 7 * PIXEL, .21), orange, pivot, .003)
    for index, (x, width) in enumerate([(-13, 3), (-5.5, 4), (5.5, 4), (12.5, 4)], 1):
        pivot = empty('PetLeg' + str(index), (x * PIXEL, -6.5 * PIXEL, 0), root)
        box('PetLeg' + str(index) + 'Mesh', (0, -4 * PIXEL, 0), (width * PIXEL, 8 * PIXEL, .20), orange, pivot, .002)
    bpy.context.view_layer.update()
    return root
