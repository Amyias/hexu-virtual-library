"""A reusable hardcover model with a genuinely recessed smart-chip pocket.
Physical size: 216 x 306 x 26 mm. A single template serves all 1280 books.
"""
import bpy
import math
import json
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1]

def pos(p):return (p[0],-p[2],p[1])
def mat(name,c,rough=.5,metal=0,alpha=1):
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name);m.use_nodes=True;m.node_tree.nodes.clear()
    s=m.node_tree.nodes.new('ShaderNodeBsdfPrincipled');o=m.node_tree.nodes.new('ShaderNodeOutputMaterial');m.node_tree.links.new(s.outputs['BSDF'],o.inputs['Surface'])
    s.inputs['Base Color'].default_value=(*c,1);s.inputs['Roughness'].default_value=rough;s.inputs['Metallic'].default_value=metal;s.inputs['Alpha'].default_value=alpha
    m.diffuse_color=(*c,alpha)
    if alpha<1:m.surface_render_method='DITHERED'
    return m

def populate():
    for cname in ['11 Book template','12 Smart books']:
        c=bpy.data.collections.get(cname)
        if c:
            for o in list(c.objects):bpy.data.objects.remove(o,do_unlink=True)
            bpy.data.collections.remove(c)
    # Clears the legacy clothbound fillers that older .blend files still carry (archive
    # backups, or a scene hand-edited before the smart-book system existed). A fresh
    # build_library.py run authors none of them, so this is normally a no-op.
    for o in list(bpy.data.objects):
        if o.name.startswith(('Clothbound volume','Page head','Spine foil','Library spine label')):bpy.data.objects.remove(o,do_unlink=True)
    scene=bpy.context.scene
    template=bpy.data.collections.new('11 Book template');scene.collection.children.link(template)
    shelfbooks=bpy.data.collections.new('12 Smart books');scene.collection.children.link(shelfbooks)
    leather=mat('Book | fine woven cover',(.075,.14,.11),.68)
    paper=mat('Book | ivory page block',(.74,.70,.57),.86)
    edge=mat('Book | page edge grooves',(.39,.34,.24),.9)
    gold=mat('Book | satin brass details',(.57,.39,.13),.34,.65)
    black=mat('Book | chip silicon',(.017,.026,.025),.4,.25)
    pcb=mat('Book | chip substrate',(.025,.065,.05),.67)
    silver=mat('Book | laser marking',(.72,.75,.65),.4,.35)
    glass=mat('Book | protective window',(.40,.55,.50),.19,0,.12)
    root=bpy.data.objects.new('BookTemplate',None);template.objects.link(root)
    hinge=bpy.data.objects.new('FrontHinge',None);template.objects.link(hinge);hinge.parent=root;hinge.location=pos((-.108,0,.011))
    def box(name,p,size,m,bevel=.0007,parent=root):
        bpy.ops.mesh.primitive_cube_add(size=1)
        o=bpy.context.object;o.name=name;o.dimensions=(size[0],size[2],size[1]);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
        if bevel:
            b=o.modifiers.new('Edge rounding','BEVEL');b.width=bevel;b.segments=2;bpy.ops.object.modifier_apply(modifier=b.name)
        for c in list(o.users_collection):c.objects.unlink(o)
        template.objects.link(o);o.parent=parent;o.location=pos(p);o.data.materials.append(m)
        return o
    box('PageBlock',(0,0,0),(.206,.294,.016),paper,.0012)
    box('RearBoard',(0,0,-.0108),(.216,.306,.0036),leather,.0012)
    box('RoundedSpine',(-.105,0,0),(.007,.304,.024),leather,.0028)
    # Front cover is assembled around an open recess, not a raised chip glued on a cube.
    cx,cy=.173,-.105 # hinge-local chip centre (.065 in book coordinates)
    cw,ch=.043,.034
    left,right=cx-cw/2,cx+cw/2;bottom,top=cy-ch/2,cy+ch/2
    box('FrontCover_top',(.108,(.153+top)/2,.0004),(.216,.153-top,.0036),leather,.0007,hinge)
    box('FrontCover_bottom',(.108,(-.153+bottom)/2,.0004),(.216,bottom+.153,.0036),leather,.0007,hinge)
    box('FrontCover_left',(left/2,cy,.0004),(left,ch,.0036),leather,.0006,hinge)
    box('FrontCover_right',((right+.216)/2,cy,.0004),(.216-right,ch,.0036),leather,.0006,hinge)
    box('RecessFloor',(cx,cy,-.0018),(cw,ch,.0009),pcb,.0004,hinge)
    # Copper contacts and silicon die sit below the outer cover plane.
    box('ChipDie',(cx,cy+.001,-.0002),(.029,.019,.0018),black,.00065,hinge)
    for sign in [-1,1]:
        for i in range(7):
            box(f'ChipContact_{sign}_{i}',(cx+sign*.017,cy-.010+i*.0032,-.0001),(.005,.0013,.0006),gold,.00015,hinge)
    for dx,dy,w,h in [(0,.016,.042,.0012),(0,-.016,.042,.0012),(-.0205,0,.0012,.033),(.0205,0,.0012,.033)]:
        box('ChipBezel',(cx+dx,cy+dy,.0017),(w,h,.001),gold,.0002,hinge)
    box('ChipWindow',(cx,cy,.0020),(.038,.028,.00045),glass,.0002,hinge)
    # Leaf-like page separations on the fore-edge, plus headbands and spine rules.
    for i in range(12):box('PageEdgeLine',(.1032,0,-.007+i*.00125),(.00035,.288,.00023),edge,0)
    for sign in [-1,1]:
        box('Headband',(-.099,sign*.146,0),(.009,.002,.016),gold,.0003)
        box('SpineFoil',(-.109,sign*.115,0),(.0003,.002,.022),gold,0)
    # Export the original hierarchy so the front cover really pivots around its spine.
    bpy.ops.object.select_all(action='DESELECT')
    for o in template.objects:o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(ROOT/'public/models/smart-book.glb'),export_format='GLB',use_selection=True,export_yup=True,export_animations=False)
    objects=list(template.objects)
    inventory=json.loads((ROOT/'blender/catalog.json').read_text(encoding='utf-8'))
    cover_colors={}
    for b in inventory:
        bookroot=bpy.data.objects.new('Book_'+b['bookId'],None);shelfbooks.objects.link(bookroot)
        bookroot.location=pos(b['worldPosition']);bookroot.rotation_euler.z=math.pi/2 if b['side']=='A' else -math.pi/2
        # The catalogue gives every volume its own width, height and thickness, the way a real
        # shelf is stocked. The book is authored upright, so in Blender its own axes are X for
        # the cover width, Y for the thickness and Z for the height; the root sits at the
        # volume's centre, so scaling leaves the book standing on its board and carries the
        # chip engraving with it.
        bookroot.scale=(b.get('widthScale',1),b.get('depthScale',1),b.get('heightScale',1))
        for k,v in b['chipPayload'].items():bookroot[k]=v
        bookroot['chip_id']=b['chipId']
        if b['color'] not in cover_colors:
            h=b['color'].lstrip('#');c=tuple((int(h[i:i+2],16)/255)**2.2 for i in (0,2,4))
            cover_colors[b['color']]=mat('Book cover '+b['color'],c,.68)
        mapping={root:bookroot}
        for o in objects:
            if o==root:continue
            clone=o.copy();clone.data=o.data;shelfbooks.objects.link(clone);mapping[o]=clone
        for o,clone in mapping.items():
            if o==root:continue
            clone.parent=mapping.get(o.parent,bookroot)
            if clone.type=='MESH' and clone.data.materials[0]==leather:
                clone.material_slots[0].link='OBJECT';clone.material_slots[0].material=cover_colors[b['color']]
        # Physical recessed microtext for the .blend close-up and subsequent editing.
        for name,text,y,size in [('ChipSerial',b['bookId'],cy+.005,.0031),('ChipPosition',b['locationCode'],cy-.003,.0020)]:
            curve=bpy.data.curves.new(name,'FONT');curve.body=text;curve.size=size;curve.align_x='CENTER';curve.extrude=.000015
            ob=bpy.data.objects.new(name+'_'+b['bookId'],curve);shelfbooks.objects.link(ob);ob.parent=mapping[hinge]
            ob.location=pos((cx,y,.0009));ob.rotation_euler=(math.pi/2,0,0);ob.data.materials.append(silver)
    template.hide_render=True
    template.hide_viewport=True
    # Counted off the inventory rather than written down, so widening a shelf face cannot
    # leave the exported manifest claiming the old capacity.
    per_face={}
    for b in inventory:per_face[(b['shelf'],b['side'],b['layer'])]=per_face.get((b['shelf'],b['side'],b['layer']),0)+1
    scene['smart_books_total']=len(inventory)
    scene['books_per_side_layer']=max(per_face.values()) if per_face else 0
    print('SMART_BOOKS_READY '+str(len(inventory)),flush=True)
    return inventory
