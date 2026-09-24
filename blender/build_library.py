"""Build an editable, dimensioned library in Blender and export a web GLB.
Run: blender --background --python blender/build_library.py
Coordinates in helper functions are Three.js X,Y(up),Z; converted at creation.
No third-party assets or Python dependencies are required.
"""
import bpy
import math
import random
import json
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'public' / 'models'
OUT.mkdir(parents=True, exist_ok=True)
TEX = ROOT / 'public' / 'textures'
TEX.mkdir(parents=True, exist_ok=True)
random.seed(20260924)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1
scene.render.engine = 'CYCLES'
scene.cycles.samples = 24
scene.cycles.use_denoising = True
scene.world.color = (.28, .28, .28)
groups = {}
current = None

def group(name):
    global current
    current = bpy.data.collections.new(name)
    scene.collection.children.link(current)
    groups[name] = current

def link(obj):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    current.objects.link(obj)
    return obj

def pos(v):
    return (v[0], -v[2], v[1])

def color(h):
    rgb = [int(h[i:i+2],16)/255 for i in (0,2,4)]
    return tuple(((v+.055)/1.055)**2.4 if v>.04045 else v/12.92 for v in rgb)+(1,)

def material(name, h, rough=.6, metallic=0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = color(h)
    m.use_nodes = True
    m.node_tree.nodes.clear()
    p = m.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
    p.name = 'Principled BSDF'
    output = m.node_tree.nodes.new('ShaderNodeOutputMaterial')
    m.node_tree.links.new(p.outputs['BSDF'], output.inputs['Surface'])
    p.inputs['Base Color'].default_value = color(h)
    p.inputs['Roughness'].default_value = rough
    p.inputs['Metallic'].default_value = metallic
    return m

oak = material('Smoked oak | UV grain', 'ad825a', .48)
walnut = material('Walnut end grain', '624932', .52)
stone = material('Warm honed limestone', 'e4dbc7', .75)
plaster = material('Mineral lime plaster', 'e9e1cf', .87)
sage = material('Sage woven upholstery', '708271', .95)
paper = material('Ivory paper edges', 'e4d9bc', .9)
brass = material('Brushed champagne brass', 'bb9b5b', .32, .65)
black = material('Dark bronze', '353e37', .4, .5)
green = material('Botanical deep green', '3e674b', .85)
green2 = material('Botanical light green', '759061', .83)
soil = material('Potting soil', '3b3427', 1)
rug = material('Woven moss carpet', '84917a', 1)
light = material('Warm opal luminaire', 'fff0ce', .35)
p=light.node_tree.nodes.get('Principled BSDF')
p.inputs['Emission Color'].default_value=color('ffe2a8')
p.inputs['Emission Strength'].default_value=2.4
book_mats=[material('Book cloth '+str(i),h,.85) for i,h in enumerate(['415f56','6d805e','a88252','8c5c47','466477','bbad8e','58516e','687a76','8e985f'])]

# Generate an actual exportable wood-grain image inside Blender (packed in .blend / GLB).
image = bpy.data.images.new('Oak grain 512', width=512, height=512, alpha=True)
pixels=[]
for y in range(512):
    for x in range(512):
        bend=math.sin(y*.013)*4+math.sin(y*.035+x*.008)*1.5
        grain=math.sin((x+bend)*.55)*.026+math.sin((x+bend)*2.7)*.012
        pore=random.random()*.025
        pixels.extend((.54+grain+pore,.365+grain+pore,.205+grain+pore,1))
image.pixels.foreach_set(pixels)
image.filepath_raw=str(TEX/'oak-grain.png')
image.file_format='PNG'
image.save()
image.pack()
nodes=oak.node_tree.nodes
tex=nodes.new('ShaderNodeTexImage');tex.image=image
oak.node_tree.links.new(tex.outputs['Color'],nodes.get('Principled BSDF').inputs['Base Color'])

# Geometry cache retains real bevelled meshes with UVs; linked duplicates are efficient to author.
cache={}
def cube(name, at, size, mat, bevel=.012):
    dims=(size[0],size[2],size[1])
    key=(tuple(round(d,5) for d in dims),round(bevel,5),mat.name)
    if key not in cache:
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj=bpy.context.object
        obj.dimensions=dims
        bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
        if bevel:
            mod=obj.modifiers.new('Crafted edge radius','BEVEL')
            mod.width=bevel;mod.segments=2
            bpy.ops.object.modifier_apply(modifier=mod.name)
        obj.data.materials.append(mat)
        cache[key]=obj.data
    else:
        obj=bpy.data.objects.new(name,cache[key]);current.objects.link(obj)
    obj.name=name;obj.location=pos(at)
    return link(obj)

def cylinder(name,at,radius,depth,mat,radius_top=None,vertices=24):
    if radius_top is None:
        bpy.ops.mesh.primitive_cylinder_add(vertices=vertices,radius=radius,depth=depth,location=pos(at))
    else:
        bpy.ops.mesh.primitive_cone_add(vertices=vertices,radius1=radius,radius2=radius_top,depth=depth,location=pos(at))
    o=link(bpy.context.object);o.name=name;o.data.materials.append(mat)
    for p in o.data.polygons:p.use_smooth=len(p.vertices)==4
    return o

def sphere(name,at,size,mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8,radius=1,location=pos(at))
    o=link(bpy.context.object);o.name=name;o.scale=(size[0],size[2],size[1]);o.data.materials.append(mat)
    for p in o.data.polygons:p.use_smooth=True
    return o

def rod(name,start,end,radius,mat):
    a,b=Vector(pos(start)),Vector(pos(end))
    o=cylinder(name,(0,0,0),radius,(b-a).length,mat,vertices=10)
    o.location=(a+b)/2;o.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler()
    return o

def text(name,value,at,size,mat):
    c=bpy.data.curves.new(name,'FONT');c.body=value;c.size=size;c.align_x='CENTER';c.extrude=.001;c.bevel_depth=.0004
    o=bpy.data.objects.new(name,c);current.objects.link(o);o.location=pos(at);o.rotation_euler=(math.pi/2,0,0);o.data.materials.append(mat)
    return o

group('01 Architecture')
cube('Floating stone foundation',(0,-.18,-1),(20,.3,19),stone,.10)
cube('Bronze reveal under floor',(0,-.30,-1),(19.85,.05,18.85),black,.01)
for x in range(20):
    for z in range(7):
        cube('Oak plank',(x-9.5,-.015,z*2.65-8.95+(x%2)*.10),(.992,.045,2.64),oak,.005)
for x in (-9.77,9.77):cube('Perimeter stone border',(x,.015,-1),(.38,.07,18.5),stone,.012)
cube('Back skirting',(0,.14,-10.2),(20,.28,.34),walnut)
cube('Rear wall base',(0,.57,-10.3),(20,1.1,.26),plaster,.02)
cube('Upper lintel',(0,4.45,-10.3),(20,.4,.28),plaster,.02)
for x in [-10,-6.67,-3.33,0,3.33,6.67,10]:
    cube('Window pier',(x,2.75,-10.3),(.26,3.5,.36),plaster,.025)
    cube('Bronze window jamb',(x+.18,2.8,-10.10),(.035,3.2,.07),brass,.005)
for x in [-8.33,-5,-1.67,1.67,5,8.33]:
    cube('Window sill',(x,1.14,-10.10),(3.03,.10,.48),stone,.025)
    cube('Window horizontal bar',(x,2.75,-10.15),(3.03,.035,.06),brass,.004)
    cube('Window vertical bar',(x,2.8,-10.15),(.035,3.15,.06),brass,.004)
    # High-level arch frame; openings remain transparent to show the garden sky.
    for i in range(20):
        t1=i*math.pi/20;t2=(i+1)*math.pi/20
        rod('Arched bronze frame',(x+1.48*math.cos(t1),3+1.25*math.sin(t1),-10.14),(x+1.48*math.cos(t2),3+1.25*math.sin(t2),-10.14),.025,brass)
cube('Garden boundary',(0,.16,-11.1),(20,.25,1.1),stone,.07)
for i in range(26):sphere('Garden shrub',(random.uniform(-10,10),.5,-11.1),(.4,.5,.4),green if i%2 else green2)

# Shelf books come entirely from the smart-book system (blender/smart_books.py): 320 chipped
# volumes that the browser instances from smart-book.glb. This build authors no static
# clothbound volumes. export_saved.py sets the same variable from the scene it re-exports.
static_books=0
shelf_manifest=[]
for s,x in enumerate([-6,-3,0,3,6],1):
    group('Shelf_'+str(s))
    # Exact finished envelope: width=1m, height=2m, length=8m.
    cube('Shelf plinth',(x,.065,-4.8),(.94,.13,7.9),walnut,.022)
    # Each face is its own bookcase with a 300 mm deep cavity behind a solid back panel —
    # the depth general collections are shelved at. A full partition between the two faces
    # (rather than a rear lip) is what lets a book stand unsupported without sliding through.
    # Panel spans centre +/-(0.17..0.20), so the face a book leans on sits 0.20 from centre.
    for side in [-1,1]:
        cube('Shelf back panel',(x+side*.185,1.04,-4.8),(.03,1.84,7.90),oak,.006)
    for y in [.055,.50,1.00,1.50,1.965]:
        cube('Shelf board',(x,y,-4.8),(1,.07,8),oak,.012)
        for side in [-1,1]:
            cube('Brass shelf lip',(x+side*.499,y+.006,-4.8),(.007,.014,7.88),brass,.002)
    for z in [-8.75,-6.8,-4.8,-2.8,-.85]:
        cube('Frame post',(x,1,z),(1,2,.1),oak,.014)
    # End panel with framed inset and a brushed brass catalogue plate.
    cube('Inset sage end panel',(x,1.08,-.792),(.72,1.43,.014),sage,.025)
    for dx in [-.4,.4]:cube('End border',(x+dx,1.08,-.773),(.018,1.6,.014),brass,.004)
    cube('Shelf number plate',(x,1.53,-.755),(.39,.27,.019),brass,.012)
    text('Shelf number',f'{s:02}',(x,1.46,-.74),.19,black)
    text('Shelf sides','B  /  A',(x,.61,-.759),.095,paper)
    shelf_manifest.append({'name':f'Shelf_{s}','dimensions_m':[1,2,8],'landing':[x,1,0],'sides':['A','B'],'layers':4})

group('06 Service desk')
cube('Desk shadow plinth',(0,.065,5),(3.3,.13,1.08),black,.055)
cube('Desk rounded core',(0,.40,5),(3.35,.67,1.07),walnut,.16)
cube('Honed stone counter',(0,.82,5),(3.62,.13,1.32),stone,.075)
for i in range(52):
    x=-1.54+i*.0604
    cube('Fluted oak fascia',(x,.43,5.555),(.038,.62,.055),oak,.017)
cube('Desk bronze badge',(0,.48,5.607),(.87,.23,.018),black,.012)
text('Desk lettering','HE XU',(0,.45,5.621),.12,brass)
cylinder('Orb docking ring',(0,.89,5),.34,.025,brass,vertices=64)
cylinder('Orb docking inset',(0,.905,5),.29,.01,black,vertices=48)
# A small angled service display and a pen tray.
o=cube('Service display',(-1.15,1.0,4.92),(.43,.27,.035),black,.018);o.rotation_euler.x=math.radians(12)
cube('Display stand',(-1.15,.9,4.95),(.15,.12,.12),brass)
cube('Paper tray',(1.1,.91,5.04),(.47,.05,.3),walnut)
cube('Desk paper',(1.1,.943,5.04),(.4,.009,.24),paper,.002)

group('07 Reading furniture')
def chair(x,z,flip=False):
    d=-1 if flip else 1
    for xx in [-.28,.28]:
        for zz in [-.24,.24]:rod('Tapered chair leg',(x+xx,.04,z+zz),(x+xx*.88,.47,z+zz*.84),.025,walnut)
    cube('Chair seat frame',(x,.45,z),(.72,.09,.67),oak,.045)
    cube('Upholstered seat',(x,.525,z),(.67,.13,.62),sage,.06)
    o=cube('Curved upholstered back',(x,.84,z+d*.28),(.70,.46,.13),sage,.062);o.rotation_euler.x=d*.10
    for xx in [-.34,.34]:
        rod('Arm support',(x+xx,.48,z+.1*d),(x+xx,.76,z+.12*d),.024,brass)
        cube('Oak armrest',(x+xx,.76,z),(.07,.055,.48),oak,.025)
for x in [-5.9,5.9]:
    cube('Inset woven reading rug',(x,.028,4.1),(3.25,.018,3.45),rug,.15)
    cylinder('Round reading table',(x,.78,4.1),.85,.095,oak,vertices=64)
    cylinder('Table brass reveal',(x,.723,4.1),.82,.016,brass,vertices=64)
    cylinder('Pedestal',(x,.39,4.1),.13,.64,walnut)
    cylinder('Table base',(x,.065,4.1),.46,.07,black,vertices=32)
    chair(x,5.30);chair(x,2.90,True)
    cylinder('Reading lamp foot',(x+.38,.847,4.12),.15,.025,brass)
    rod('Reading lamp stem',(x+.38,.85,4.12),(x+.38,1.23,4.12),.018,brass)
    cylinder('Opal shade',(x+.38,1.28,4.12),.21,.15,light,.09,32)
    for k in range(3):cube('Table book stack',(x-.22,.861+k*.035,4.07),(.4,.03,.28),book_mats[k],.006)

group('08 Botanical details')
def plant(x,z,scale=1):
    cylinder('Ceramic tapered planter',(x,.29,z),.25,.58,stone,.34,32)
    cylinder('Planter rim',(x,.59,z),.35,.04,stone,vertices=32)
    cylinder('Visible soil',(x,.606,z),.31,.01,soil)
    for i in range(12):
        a=i*2.4;h=random.uniform(.55,1.0)*scale;r=random.uniform(.25,.47)*scale
        tip=(x+math.cos(a)*r,.6+h,z+math.sin(a)*r)
        rod('Leaf stem',(x,.61,z),tip,.009,green)
        leaf=sphere('Lanceolate leaf',tip,(.105*scale,.26*scale,.035*scale),green if i%2 else green2)
        leaf.rotation_euler=(.35*math.sin(a),.5*math.cos(a),a)
for x,z,s in [(-8.7,5.1,1.2),(8.7,5.1,1.2),(-8.5,-8.9,1.4),(8.5,-8.9,1.4),(-8.7,-2,1),(8.7,-2,1)]:plant(x,z,s)

group('09 Suspended lighting')
for x in [-4.5,-1.5,1.5,4.5]:
    for z in [-6.8,-2.5]:
        rod('Suspension cable',(x,4.5,z),(x,3.72,z),.006,black)
        cube('Linear bronze pendant',(x,3.68,z),(.09,.11,1.35),brass,.025)
        cube('Pendant diffuser',(x,3.618,z),(.06,.012,1.25),light,.006)

# Save the fully editable source BEFORE merging static export meshes.
# The botanical module also replaces the initial blockout when rebuilding from scratch.
import sys
sys.path.insert(0,str(ROOT/'blender'))
from vegetation import populate
vegetation_stats=populate()
groups.update({c.name:c for c in bpy.data.collections if c.name.startswith('08 ')})
(ROOT/'blender'/'vegetation-manifest.json').write_text(json.dumps(vegetation_stats,ensure_ascii=False,indent=2),encoding='utf-8')
from smart_books import populate as populate_books
populate_books()
group('10 Render rig')
def area(name,at,power,size,target):
    data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size
    obj=bpy.data.objects.new(name,data);current.objects.link(obj);obj.location=pos(at);obj.rotation_euler=(Vector(pos(target))-obj.location).to_track_quat('-Z','Y').to_euler()
area('Large softbox',(-4,12,5),2200,9,(0,0,-3))
area('Window daylight',(1,7,-9),1800,8,(0,0,-3))
data=bpy.data.cameras.new('Library overview');cam=bpy.data.objects.new('Library overview',data);current.objects.link(cam)
cam.location=pos((16,16,23));cam.rotation_euler=(Vector(pos((0,.6,-1)))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=28;scene.camera=cam
scene.render.resolution_x=1500;scene.render.resolution_y=1100;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.filepath=str(ROOT/'blender'/'library-preview.png')
scene['model_spec']='Five 8m x 1m x 2m double-sided shelves, four book layers; metres; +Y up on glTF export.'
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'blender'/'hexu-library.blend'))
print('EDITABLE_BLEND_SAVED',flush=True)

# Merge by collection + material for low draw-call web delivery. Source remains editable.
# Millimetre foil rules and paper edges do not need bevel loops in a browser.
# Keep those detailed bevels in the editable .blend, simplify only this export copy.
detail_cache={}
for obj in list(bpy.data.objects):
    if obj.type!='MESH' or not obj.name.startswith(('Spine foil','Library spine label','Page head')):continue
    lo=[min(v.co[i] for v in obj.data.vertices) for i in range(3)]
    hi=[max(v.co[i] for v in obj.data.vertices) for i in range(3)]
    mat=obj.data.materials[0]
    key=(tuple(round(v,6) for v in lo+hi),mat.name)
    if key not in detail_cache:
        mesh=bpy.data.meshes.new('Web micro-detail')
        verts=[(lo[0],lo[1],lo[2]),(hi[0],lo[1],lo[2]),(hi[0],hi[1],lo[2]),(lo[0],hi[1],lo[2]),(lo[0],lo[1],hi[2]),(hi[0],lo[1],hi[2]),(hi[0],hi[1],hi[2]),(lo[0],hi[1],hi[2])]
        mesh.from_pydata(verts,[],[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])
        mesh.materials.append(mat);mesh.update();detail_cache[key]=mesh
    obj.data=detail_cache[key]
for name,coll in groups.items():
    if name in ('10 Render rig','11 Book template','12 Smart books'):continue
    candidates=list(coll.objects)
    for o in candidates:
        if o.type=='FONT':
            bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o;bpy.ops.object.convert(target='MESH')
    buckets={}
    for o in list(coll.objects):
        if o.type=='MESH':buckets.setdefault(o.data.materials[0].name if o.data.materials else 'none',[]).append(o)
    for matname,objects in buckets.items():
        bpy.ops.object.select_all(action='DESELECT')
        for o in objects:o.select_set(True)
        bpy.context.view_layer.objects.active=objects[0]
        # Joining into linked data otherwise changes unselected instances in other shelves.
        objects[0].data = objects[0].data.copy()
        if len(objects)>1:bpy.ops.object.join()
        bpy.context.object.name=name+'__'+matname

bpy.ops.object.select_all(action='DESELECT')
mesh_objects=[]
for name,coll in groups.items():
    if name in ('10 Render rig','11 Book template','12 Smart books'):continue
    for o in coll.objects:
        if o.type=='MESH':o.select_set(True);mesh_objects.append(o)
triangles=sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in mesh_objects)
print('EXPORT_AUDIT meshes='+str(len(mesh_objects))+' triangles='+str(triangles),flush=True)
if triangles>1000000:raise RuntimeError('Unexpected geometry expansion during export')
bpy.ops.export_scene.gltf(filepath=str(OUT/'hexu-library.glb'),export_format='GLB',use_selection=True,export_yup=True,export_apply=True,export_extras=True,export_animations=False)
manifest={'generator':bpy.app.version_string,'source':'blender/hexu-library.blend','model':'public/models/hexu-library.glb','shelves':shelf_manifest,'static_books':static_books,'mesh_objects':len(mesh_objects),'triangles':triangles,'bytes':(OUT/'hexu-library.glb').stat().st_size,'texture':'public/textures/oak-grain.png'}
manifest['interactive_books']=int(scene.get('smart_books_total',0))
manifest['books_per_side_layer']=int(scene.get('books_per_side_layer',0))
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('MODEL_EXPORT_OK '+json.dumps(manifest),flush=True)
bpy.ops.render.render(write_still=True)
print('PREVIEW_RENDER_OK',flush=True)
