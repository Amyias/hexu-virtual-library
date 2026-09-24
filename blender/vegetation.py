"""Reference-guided leaf geometry; no imported photographic textures.
All mesh vertices are specified in Three.js X/Y-up/Z metres, converted once.
"""
import bpy
import math
import random
import json
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
TAU = math.tau

def p(v): return (v[0], -v[2], v[1])

def mat(name, rgb, rough=.55):
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes=True;m.diffuse_color=(*rgb,1)
    m.node_tree.nodes.clear()
    s=m.node_tree.nodes.new('ShaderNodeBsdfPrincipled');s.name='Principled BSDF'
    s.inputs['Base Color'].default_value=(*rgb,1)
    s.inputs['Roughness'].default_value=rough
    s.inputs['Coat Weight'].default_value=.10
    out=m.node_tree.nodes.new('ShaderNodeOutputMaterial')
    m.node_tree.links.new(s.outputs['BSDF'],out.inputs['Surface'])
    m.use_backface_culling=False
    return m

class Mesh:
    """One editable mesh per plant/material, not one object per small leaf."""
    def __init__(self,name,material):
        self.name=name;self.material=material;self.verts=[];self.faces=[];self.uv=[]
    def vertex(self,co,uv=(0,0)):
        self.verts.append(p(co));self.uv.append(uv);return len(self.verts)-1
    def finish(self,collection):
        if not self.verts:return
        m=bpy.data.meshes.new(self.name);m.from_pydata(self.verts,[],self.faces);m.materials.append(self.material);m.update()
        uv=m.uv_layers.new(name='Leaf UV')
        for poly in m.polygons:
            poly.use_smooth=True
            for loop in poly.loop_indices:uv.data[loop].uv=self.uv[m.loops[loop].vertex_index]
        o=bpy.data.objects.new(self.name,m);collection.objects.link(o)
        return o

def tube(mesh,points,radius,sides=6,end_scale=.4):
    pts=[Vector(v) for v in points];rows=[]
    for i,point in enumerate(pts):
        direction=(pts[min(i+1,len(pts)-1)]-pts[max(0,i-1)]).normalized()
        reference=Vector((0,1,0)) if abs(direction.y)<.9 else Vector((1,0,0))
        right=direction.cross(reference).normalized();up=direction.cross(right).normalized()
        r=radius*(1-(1-end_scale)*i/(len(pts)-1))
        rows.append([mesh.vertex(point+r*(right*math.cos(j*TAU/sides)+up*math.sin(j*TAU/sides))) for j in range(sides)])
    for i in range(len(rows)-1):
        for j in range(sides):mesh.faces.append((rows[i][j],rows[i][(j+1)%sides],rows[i+1][(j+1)%sides],rows[i+1][j]))
    mesh.faces.append(tuple(reversed(rows[0])));mesh.faces.append(tuple(rows[-1]))

def lathe(mesh,x,z,profile,segments=64,flute=0):
    rows=[]
    for radius,y in profile:
        rows.append([mesh.vertex((x+(radius+flute*math.cos(j*TAU/segments*32))*math.cos(j*TAU/segments),y,z+(radius+flute*math.cos(j*TAU/segments*32))*math.sin(j*TAU/segments))) for j in range(segments)])
    for a,b in zip(rows,rows[1:]):
        for j in range(segments):mesh.faces.append((a[j],b[j],b[(j+1)%segments],a[(j+1)%segments]))

def leaf(mesh,base,direction,length,width,rng,rows=14,columns=6,curl=.09,split=False):
    base=Vector(base);d=Vector(direction).normalized()
    ref=Vector((0,1,0)) if abs(d.y)<.92 else Vector((1,0,0))
    right=d.cross(ref).normalized();normal=right.cross(d).normalized()
    twist=rng.uniform(-.45,.45)
    right,normal=right*math.cos(twist)+normal*math.sin(twist),normal*math.cos(twist)-right*math.sin(twist)
    phase=rng.random()*TAU;grid=[];mid=[]
    for i in range(rows+1):
        t=i/rows
        center=base+d*(length*t)+Vector((0,-curl*t*t,0))+normal*(math.sin(t*math.pi)*length*.055)
        mid.append(center)
        breadth=max(.004,math.sin(math.pi*t)**.70)*width*(.94+.06*math.sin(t*8+phase))
        row=[]
        for j in range(columns+1):
            q=j/columns*2-1
            notch=.80 if split and i==int(rows*.72) and abs(q)>.65 else 1
            ripple=math.sin(t*35+phase)*.010*abs(q)**2*length
            fold=(1-abs(q))*.009-math.sin(abs(q)*math.pi*.5)*.027*length
            co=center+right*(q*breadth*notch)+normal*(fold+ripple)
            row.append(mesh.vertex(co,(j/columns,t)))
        grid.append(row)
    for i in range(rows):
        for j in range(columns):mesh.faces.append((grid[i][j],grid[i][j+1],grid[i+1][j+1],grid[i+1][j]))
    return mid

def leaf_texture():
    size=512;rng=random.Random(61);pixels=[]
    image=bpy.data.images.new('Botanical lamina | midrib and lateral veins',width=size,height=size)
    for y in range(size):
        t=y/(size-1)
        for x in range(size):
            q=abs(x/(size-1)*2-1)
            central=math.exp(-(q/.018)**2)
            lateral=math.exp(-(math.sin((t-q*.20)*math.pi*25)/.15)**2)
            sheen=.017*math.sin(t*21+q*7)+rng.uniform(-.009,.009)
            edge=q*q*.025
            pixels.extend((.105+central*.13+lateral*.022+sheen,.255+central*.17+lateral*.041+sheen-edge,.064+central*.035+lateral*.007+sheen*.4,1))
    image.pixels.foreach_set(pixels)
    path=ROOT/'public'/'textures'/'botanical-leaf.png';path.parent.mkdir(parents=True,exist_ok=True)
    image.filepath_raw=str(path);image.file_format='PNG';image.save();image.pack()
    return image

def populate(shrub_positions=None):
    rng=random.Random(724);scene=bpy.context.scene
    # Remove only the two botanical collections and the old outdoor sphere placeholders.
    for name in ['08 Botanical details','08 Exterior shrubs']:
        coll=bpy.data.collections.get(name)
        if coll:
            for obj in list(coll.objects):bpy.data.objects.remove(obj,do_unlink=True)
            bpy.data.collections.remove(coll)
    old=[o for o in bpy.data.objects if o.name.startswith('Garden shrub')]
    if shrub_positions is None:
        shrub_positions=[(o.location.x,-o.location.y) for o in old]
        if not shrub_positions and scene.get('vegetation_shrub_positions'):
            shrub_positions=json.loads(scene['vegetation_shrub_positions'])
    for o in old:bpy.data.objects.remove(o,do_unlink=True)
    if not shrub_positions:shrub_positions=[(-9.65+i*19.3/25,-11.1) for i in range(26)]
    scene['vegetation_shrub_positions']=json.dumps(shrub_positions)
    pots=bpy.data.collections.new('08 Botanical details');scene.collection.children.link(pots)
    hedge=bpy.data.collections.new('08 Exterior shrubs');scene.collection.children.link(hedge)
    ceramic=mat('Botanical | ivory ribbed ceramic',(.61,.57,.47),.72)
    rim=mat('Botanical | glazed rim',(.68,.65,.55),.29)
    soil=mat('Botanical | soil',(.038,.025,.015),.98)
    bark=mat('Botanical | woody branches',(.13,.072,.028),.88)
    petiole=mat('Botanical | petiole',(.12,.24,.055),.47)
    rib=mat('Botanical | raised midrib',(.25,.35,.09),.5)
    pebble=mat('Botanical | mineral granules',(.20,.17,.12),.95)
    image=leaf_texture()
    big=[]
    for i in range(3):
        m=mat('Botanical | Strelitzia lamina '+str(i),(.09,.21,.04),.48+i*.06)
        n=m.node_tree.nodes.new('ShaderNodeTexImage');n.image=image
        m.node_tree.links.new(n.outputs['Color'],m.node_tree.nodes['Principled BSDF'].inputs['Base Color']);big.append(m)
    small=[mat('Botanical | boxwood leaf '+str(i),rgb,.40+i*.045) for i,rgb in enumerate([(.038,.13,.022),(.055,.19,.029),(.094,.24,.037),(.15,.28,.058)])]
    count_large=0;count_small=0
    for pi,(x,z,scale) in enumerate([(-8.7,5.1,1.2),(8.7,5.1,1.2),(-8.5,-8.9,1.4),(8.5,-8.9,1.4),(-8.7,-2,1),(8.7,-2,1)]):
        name=f'Plant_{pi+1:02}'
        shell=Mesh(name+' ceramic shell',ceramic)
        lathe(shell,x,z,[(.0,.04),(.245,.04),(.26,.075),(.27,.14),(.302,.46),(.326,.57),(.326,.605),(.296,.605),(.29,.565),(.242,.13),(.0,.13)],96,.003)
        shell.finish(pots)
        lip=Mesh(name+' rolled lip',rim);lathe(lip,x,z,[(.327,.581),(.333,.595),(.326,.612),(.296,.612),(.290,.596)],96);lip.finish(pots)
        dirt=Mesh(name+' recessed soil',soil);lathe(dirt,x,z,[(0,.546),(.286,.546)],48);dirt.finish(pots)
        grit=Mesh(name+' soil granules',pebble)
        for i in range(44):
            a=rng.random()*TAU;r=math.sqrt(rng.random())*.275
            pos=Vector((x+math.cos(a)*r,.551,z+math.sin(a)*r));sz=rng.uniform(.006,.013)
            ids=[grit.vertex(pos+Vector(v)*sz) for v in [(1,0,0),(0,.7,1),(-1,0,0),(0,.5,-1),(0,1.2,0)]]
            grit.faces.extend([(ids[0],ids[1],ids[4]),(ids[1],ids[2],ids[4]),(ids[2],ids[3],ids[4]),(ids[3],ids[0],ids[4])])
        grit.finish(pots)
        stems=Mesh(name+' curved petioles',petiole);veins=Mesh(name+' sculpted midribs',rib)
        blades=[Mesh(name+' leaf blades '+str(i),m) for i,m in enumerate(big)]
        for k in range(9):
            a=k*2.399+pi*.57+rng.uniform(-.2,.2)
            outward=Vector((math.cos(a),0,math.sin(a)))
            foot=Vector((x,.55,z))+outward*rng.uniform(.035,.12)
            h=(.53+.085*k)*scale
            base=Vector((x,.57+h,z))+outward*(.16+.022*k)*scale
            pts=[foot.lerp(base,t)+outward*(math.sin(t*math.pi)*.045) for t in [0,.2,.4,.6,.8,1]]
            tube(stems,pts,.016*scale,7,.5)
            direction=outward+Vector((0,.27+(k/8)*.8,0))
            length=rng.uniform(.53,.75)*scale;width=rng.uniform(.12,.17)*scale
            mid=leaf(blades[k%3],base,direction,length,width,rng,16,8,.20*scale,k%3==0)
            tube(veins,[v+Vector((0,.003,0)) for v in mid],.0021*scale,5,.10)
            count_large+=1
        # A pale rolled spear leaf marks the growing centre.
        bud=Vector((x+.02,2.02*scale,z+.04));tube(stems,[(x,.56,z),(.5*(x+bud.x),1.25*scale,.5*(z+bud.z)),bud],.018,7,.2)
        stems.finish(pots);veins.finish(pots)
        for b in blades:b.finish(pots)
    # Rounded hedge silhouette formed by small leaves; no hidden ball cores.
    mulch=Mesh('Shrub bed | recessed organic soil',soil)
    mulch.faces.append(tuple(mulch.vertex(co) for co in [(-9.85,.291,-11.53),(-9.85,.291,-10.67),(9.85,.291,-10.67),(9.85,.291,-11.53)]))
    mulch.finish(hedge)
    for si,(x,z) in enumerate(shrub_positions):
        branches=Mesh(f'Shrub_{si+1:02} branching wood',bark)
        leaves=[Mesh(f'Shrub_{si+1:02} foliage '+str(i),m) for i,m in enumerate(small)]
        height=rng.uniform(.58,.76);radius=rng.uniform(.34,.46)
        root=Vector((x,.285,z));crown=Vector((x,.34+height*.53,z))
        tube(branches,[root,root+Vector((.015,height*.35,.01)),crown],.018,7,.6)
        for j in range(34):
            a=j*2.399+rng.uniform(-.4,.4)
            elev=rng.uniform(-.88,1)
            direction=Vector((math.cos(a)*math.sqrt(1-elev*elev),elev,math.sin(a)*math.sqrt(1-elev*elev)))
            tip=crown+Vector((direction.x*radius,direction.y*height*.58,direction.z*radius))
            start=root+Vector((0,height*.13,0))
            bend=start.lerp(tip,.30)+Vector((0,.025,0))
            tube(branches,[start,bend,tip],.0045,5,.28)
            axis=(tip-bend).normalized()
            sideways=axis.cross(Vector((0,1,0)))
            if sideways.length<.01:sideways=Vector((1,0,0))
            sideways.normalize()
            for n in range(8):
                t=.12+n*.12;base=bend.lerp(tip,t)
                for sign in [-1,1]:
                    leafdir=(sideways*sign+axis*.32+Vector((0,rng.uniform(.12,.55),0))).normalized()
                    size=rng.uniform(.046,.075)*(1-.2*t)
                    m=leaves[min(3,max(0,int((tip.y-.3)/height*4)+rng.choice([-1,0,0,1])))]
                    leaf(m,base,leafdir,size,size*.39,rng,3,2,.008,False)
                    count_small+=1
        branches.finish(hedge)
        for l in leaves:l.finish(hedge)
    stats={'potted_plants':6,'large_leaves':count_large,'shrubs':len(shrub_positions),'small_leaves':count_small,'reference_species':['Strelitzia nicolai','Buxus sempervirens'],'leaf_texture':'public/textures/botanical-leaf.png'}
    scene['vegetation_v2']=str(stats)
    return stats
