"""Surgically upgrade plants in the existing .blend, preserving other objects."""
import bpy
import sys
import json
import shutil
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'blender'))
from vegetation import populate

def invariant():
    return {o.name:(o.type,tuple(round(v,5) for row in o.matrix_world for v in row),len(o.data.polygons) if o.type=='MESH' else 0)
            for o in bpy.data.objects if not o.name.startswith('Garden shrub') and not any(c.name.startswith('08 ') for c in o.users_collection)}
backup=ROOT/'archive'/'hexu-library-before-botanical.blend'
if not backup.exists():shutil.copy2(ROOT/'blender'/'hexu-library.blend',backup)
before=invariant()
stats=populate()
assert before==invariant(),'Unrelated scene objects changed'
stats['unchanged_objects']=len(before)
(ROOT/'blender'/'vegetation-manifest.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'blender'/'hexu-library.blend'))
print('VEGETATION_SOURCE_VERIFIED '+json.dumps(stats),flush=True)
# Export uses the standard material-batching pipeline.
exec(compile((ROOT/'blender'/'export_saved.py').read_text(encoding='utf-8'),str(ROOT/'blender'/'export_saved.py'),'exec'))

# Real Cycles close-ups: pot/lamina and an exterior section of hedge.
scene=bpy.context.scene
cam=scene.camera
def at(x,y,z):return Vector((x,-z,y))
scene.render.resolution_x=1200;scene.render.resolution_y=1100
cam.data.type='ORTHO'
for name,eye,target,ortho in [
    ('plant-detail',( -5.7,3.0,8.3),(-8.7,1.25,5.1),3.35),
    ('hedge-detail',(0,2.7,-15.5),(0,.68,-11.1),5.5)]:
    cam.location=at(*eye);cam.rotation_euler=(at(*target)-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.ortho_scale=ortho
    scene.render.filepath=str(ROOT/'blender'/f'{name}.png')
    bpy.ops.render.render(write_still=True)
print('BOTANICAL_DETAIL_RENDERS_OK',flush=True)
