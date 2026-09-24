"""Export/render the saved editable scene without rebuilding or overwriting it.
blender --background --factory-startup blender/hexu-library.blend --python blender/export_saved.py
"""
import bpy
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'public'/'models'
scene=bpy.context.scene
groups={c.name:c for c in bpy.data.collections if c.name!='Collection'}
# Reports the clothbound volumes actually present in the scene being re-exported. A build from
# blender/build_library.py authors none (the 320 shelf copies come from smart-book.glb), while a
# re-export of an older, hand-edited .blend still counts whatever fillers it contains.
static_books=sum(o.name.startswith('Clothbound volume') for o in bpy.data.objects)
shelf_manifest=[{'name':f'Shelf_{i+1}','dimensions_m':[1,2,8],'landing':[x,1,0],'sides':['A','B'],'layers':4} for i,x in enumerate([-6,-3,0,3,6])]
script=(ROOT/'blender'/'build_library.py').read_text(encoding='utf-8')
exec(compile(script[script.index('# Merge by collection'):],str(ROOT/'blender'/'build_library.py'),'exec'))
