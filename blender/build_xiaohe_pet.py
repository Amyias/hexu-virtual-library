"""Build only the companion, verify other assets unchanged, then export and render its studio."""
import bpy
import sys
import json
import hashlib
from pathlib import Path
from mathutils import Vector
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'blender'))
from xiaohe_pet import create_pet, material, PIXEL
PROTECTED = ['blender/hexu-library.blend', 'public/models/hexu-library.glb',
             'public/models/smart-book.glb', 'public/models/shelf-book.glb', 'public/models/book-inventory.json']

def snapshot():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PROTECTED if (ROOT / name).exists()}

before = snapshot()
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
root = create_pet()
objects = [root, *root.children_recursive]
meshes = [obj for obj in objects if obj.type == 'MESH']
assert len(meshes) == 9, len(meshes)
for obj in meshes: obj.data.calc_loop_triangles()
triangles = sum(len(obj.data.loop_triangles) for obj in meshes)
assert triangles < 2500, triangles
points = [obj.matrix_world @ Vector(v) for obj in meshes for v in obj.bound_box]
bounds = [min(v[i] for v in points) for i in range(3)], [max(v[i] for v in points) for i in range(3)]
assert abs(bounds[1][0] - bounds[0][0] - .78) < 1e-5
assert abs(bounds[1][2] - bounds[0][2] - 29 * PIXEL) < 1e-5
out = ROOT / 'public/models'; out.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='DESELECT')
for obj in objects: obj.select_set(True)
bpy.context.view_layer.objects.active = root
bpy.ops.export_scene.gltf(filepath=str(out / 'xiaohe-pet.glb'), export_format='GLB', use_selection=True,
                          export_yup=True, export_extras=True, export_animations=False, export_cameras=False, export_lights=False)
# Studio remains in the editable blend but is never exported to the browser asset.
scene.render.engine = 'CYCLES'; scene.cycles.samples = 32; scene.cycles.use_denoising = True
scene.render.resolution_x = 900; scene.render.resolution_y = 900; scene.render.resolution_percentage = 100
scene.world.color = (.5, .5, .5)
scene.view_settings.view_transform = 'AgX'
bpy.ops.mesh.primitive_plane_add(size=200, location=(0,0,-.285))
ground=bpy.context.object; ground.name='StudioGround'; ground.data.materials.append(material('Studio warm paper','F6F3EB',.9))
for name, location, energy, size in [('StudioKey',(-2,-3,4),350,4),('StudioFill',(3,-1,2),140,3),('StudioRim',(0,3,3),250,3)]:
    light=bpy.data.lights.new(name,'AREA'); light.energy=energy; light.shape='DISK'; light.size=size
    obj=bpy.data.objects.new(name,light); scene.collection.objects.link(obj); obj.location=location
    obj.rotation_euler=(Vector((0,0,0))-obj.location).to_track_quat('-Z','Y').to_euler()
camera_data=bpy.data.cameras.new('PetStudioCamera');camera=bpy.data.objects.new('PetStudioCamera',camera_data);scene.collection.objects.link(camera)
scene.camera=camera; camera_data.type='ORTHO'; camera_data.ortho_scale=1.18
camera.location=(1.25,-2.8,1.2); camera.rotation_euler=(Vector((0,0,0))-camera.location).to_track_quat('-Z','Y').to_euler()
for view, eye in [('three-quarter',(1.25,-2.8,1.2)),('front',(0,-3,0))]:
    camera.location=eye; camera.rotation_euler=(Vector((0,0,0))-camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str(ROOT/'blender'/('xiaohe-pet-'+view+'.png'))
    bpy.ops.render.render(write_still=True)
camera.location=(1.25,-2.8,1.2); camera.rotation_euler=(Vector((0,0,0))-camera.location).to_track_quat('-Z','Y').to_euler()
assert snapshot()==before, 'An unrelated library/model asset changed'
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'blender/xiaohe-pet.blend'))
manifest={'meshes':len(meshes),'triangles':triangles,'nodes':len(objects),'width_m':.78,'height_m':29*PIXEL,'depth_m':.26,
          'color':'#D87656','eyes':2,'arms':2,'legs':4,'protected_assets':before,
          'glb_bytes':(out/'xiaohe-pet.glb').stat().st_size}
(ROOT/'blender/xiaohe-pet-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print('XIAOHE_PET_VERIFIED '+json.dumps(manifest),flush=True)
