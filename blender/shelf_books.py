"""The volume as it stands on a shelf, spine to the aisle.

The interactive book (smart-book.glb) is a full hardcover: covers, page block, a recessed chip
pocket. None of that is visible once the book is shelved with its spine out — a reader sees the
spine, the page edge along the top, and nothing else. Shelving also needs far more volumes than
the old cover-out display did: a bay of 1.84 m holds roughly seventy 25 mm spines, not eight
216 mm covers. So this template is deliberately thin — spine and top edge, two mesh parts,
one shared spine texture — and the browser can instance ten thousand of them for less than the
old cover-out wall cost.

Local axes match the interactive template, so one catalogue can drive both: X is the cover's
width (into the shelf now), Y the height, Z the thickness (the spine's width, the axis a row
packs along).
"""
import bpy
import math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WIDTH,HEIGHT,DEPTH=.216,.306,.026
SPINE_BOARD=.012      # how far the spine slab reaches into the book
BAND=.006             # gilt rule position, from the head and the tail

def pos(p):return (p[0],-p[2],p[1])

def mat(name,c,rough=.5,metal=0,image=None):
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name);m.use_nodes=True;m.node_tree.nodes.clear()
    s=m.node_tree.nodes.new('ShaderNodeBsdfPrincipled');o=m.node_tree.nodes.new('ShaderNodeOutputMaterial');m.node_tree.links.new(s.outputs['BSDF'],o.inputs['Surface'])
    s.inputs['Base Color'].default_value=(*c,1);s.inputs['Roughness'].default_value=rough;s.inputs['Metallic'].default_value=metal
    m.diffuse_color=(*c,1)
    if image:
        tex=m.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image;tex.interpolation='Cubic'
        m.node_tree.links.new(tex.outputs['Color'],s.inputs['Base Color'])
    return m

def spine_texture():
    """Cloth with two gilt rules, drawn top and tail the way a bound spine is tooled.

    Drawn here rather than fetched: it has to be embedded in the GLB (the page never loads a
    separate file for a surface this small), and the rules have to sit at fixed fractions of
    the height so every volume wears them in the same place. The cloth itself is left near
    white, because the renderer multiplies its per-instance cloth colour over this image —
    tinting a mid-tone here would darken every book twice."""
    size=256
    image=bpy.data.images.new('shelf-spine-cloth',width=size,height=size,alpha=False)
    px=[0.0]*(size*size*4)
    for y in range(size):
        for x in range(size):
            v=y/size
            # A fine vertical weave, plus the two rules at 12% and 88% of the height.
            weave=.955+.045*math.sin(x*math.pi/2.0)
            weave*=0.97+0.03*math.sin(y*math.pi/1.5)
            r,g,b=weave,weave,weave
            for at in (.12,.88):
                if abs(v-at)<.022:
                    r,g,b=(0.72,0.55,0.24)
                elif abs(v-at)<.030:
                    r,g,b=(weave*0.55,weave*0.55,weave*0.58)
            i=((y*size+x)*4)
            px[i],px[i+1],px[i+2],px[i+3]=r,g,b,1.0
    image.pixels=px
    image.pack()
    return image

def box(name,at,size,material,bevel=.0007,segments=2):
    """One part of the template, placed in book-local metres (x width, y height, z thickness).

    Blender is Z-up, so sizes and positions are converted on the way in — the same conversion
    smart-book.glb uses, because the two templates have to share one catalogue and one frame.
    Skipping it lays the volume down: its height ends up on the thickness axis, which only shows
    up as books that are 26 mm tall and 306 mm deep once the renderer scales them.
    """
    bpy.ops.mesh.primitive_cube_add(size=1)
    o=bpy.context.object;o.name=name
    o.dimensions=(size[0],size[2],size[1])
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    if bevel:
        b=o.modifiers.new('Edge rounding','BEVEL');b.width=bevel;b.segments=segments
        bpy.ops.object.modifier_apply(modifier=b.name)
    o.location=pos(at);o.data.materials.append(material)
    # Box UVs put the whole texture on every face, which is what the spine wants: a strip whose
    # rules run across the thickness and sit at fixed fractions of the height.
    return o

def build_template():
    """Create (or rebuild) the shelf-book collection and return it with its mesh parts."""
    for cname in ['13 Shelf book']:
        c=bpy.data.collections.get(cname)
        if c:
            for o in list(c.objects):bpy.data.objects.remove(o,do_unlink=True)
            bpy.data.collections.remove(c)
    scene=bpy.context.scene
    collection=bpy.data.collections.new('13 Shelf book');scene.collection.children.link(collection)
    cloth=mat('Shelf book | cloth spine',(.86,.86,.86),.72,image=spine_texture())
    paper=mat('Shelf book | page edge',(.74,.70,.57),.86)
    root=bpy.data.objects.new('ShelfBook',None);collection.objects.link(root)
    for obj in list(bpy.context.selected_objects):obj.select_set(False)
    parts=[]
    # Spine slab: the back of the book, its outer face at x = -WIDTH/2, so a row packs on Z.
    parts.append(box('Spine',(-WIDTH/2+SPINE_BOARD/2,0,0),(SPINE_BOARD,HEIGHT-.002,DEPTH-.002),cloth,.003))
    # Page edge along the top: what a reader sees looking down at a shelved row.
    parts.append(box('PageTop',(SPINE_BOARD/2,HEIGHT/2-.0015,0),(WIDTH-SPINE_BOARD,0.003,DEPTH-.004),paper,.0008))
    for o in parts:
        for c in list(o.users_collection):c.objects.unlink(o)
        collection.objects.link(o);o.parent=root
    return collection, parts

def populate():
    collection, parts = build_template()
    bpy.ops.object.select_all(action='DESELECT')
    for o in collection.objects:o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(ROOT/'public/models/shelf-book.glb'),export_format='GLB',use_selection=True,export_yup=True,export_animations=False,export_extras=True)
    stats={'parts':len(parts),'triangles':sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in parts)}
    print('SHELF_BOOK_READY '+str(stats),flush=True)
    return stats
