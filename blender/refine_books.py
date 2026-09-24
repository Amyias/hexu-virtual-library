import bpy
import sys
import shutil
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'blender'))
from smart_books import populate
backup=ROOT/'archive/hexu-library-before-chips.blend'
if not backup.exists():shutil.copy2(ROOT/'blender/hexu-library.blend',backup)
inventory=populate()
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'blender/hexu-library.blend'))
exec(compile((ROOT/'blender/export_saved.py').read_text(encoding='utf-8'),str(ROOT/'blender/export_saved.py'),'exec'))
# Source-books were omitted only from the web environment selection, not from the render.
scene=bpy.context.scene;cam=scene.camera
scene.render.resolution_x=1300;scene.render.resolution_y=1100
cam.data.type='ORTHO';cam.data.ortho_scale=.40
b=inventory[0];x,y,z=b['worldPosition']
target=Vector((x,-z,y));cam.location=target+Vector((.50,.08,.07));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
scene.render.filepath=str(ROOT/'blender/smart-book-detail.png');bpy.ops.render.render(write_still=True)
target+=Vector((.013,.065,-.105));cam.location=target+Vector((.30,.012,.015));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.ortho_scale=.065
scene.render.filepath=str(ROOT/'blender/chip-detail.png');bpy.ops.render.render(write_still=True)
# Shelf interior: the volume stands on the board and leans back on the solid back panel.
# Framed at the top layer, which catches the softbox; the offsets were picked by rendering
# candidates, because a deeper book sits in the shelf's own shadow.
shelf=next(b for b in inventory if b['shelf']==5 and b['side']=='A' and b['layer']==4 and b['slot']==5)
x,y,z=shelf['worldPosition']
t=Vector((x,-z,y))
cam.data.ortho_scale=.85
cam.location=t+Vector((.78,.50,.16));cam.rotation_euler=(t-cam.location).to_track_quat('-Z','Y').to_euler()
scene.render.filepath=str(ROOT/'blender/shelf-detail.png');bpy.ops.render.render(write_still=True)
print('BOOK_AND_CHIP_RENDERS_OK',flush=True)
