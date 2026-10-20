"""Read an isolated scene, bake ground contact AO and render a daylight reference; never save it."""
import json,os,pathlib
import bpy
from mathutils import Vector

ROOT=pathlib.Path(__file__).resolve().parents[1]
WORK=pathlib.Path(os.environ['HEXU_LIGHTING_WORK']).resolve()
bpy.ops.wm.open_mainfile(filepath=str(WORK/'blender/hexu-library.blend'))
scene=bpy.context.scene
snapshot={o.name:(tuple(v for row in o.matrix_world for v in row),len(o.data.vertices),len(o.data.polygons))
          for o in scene.objects if o.type=='MESH'}
scene.render.engine='CYCLES'
scene.cycles.samples=24
scene.cycles.use_denoising=True
scene.render.threads_mode='FIXED';scene.render.threads=8
scene.render.resolution_x=900;scene.render.resolution_y=650;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
output=WORK/'public/textures';output.mkdir(parents=True,exist_ok=True)
mode=os.environ.get('HEXU_LIGHTING_MODE','bake')
if mode=='before':
    scene.render.filepath=str(WORK/'blender-before.png')
    bpy.ops.render.render(write_still=True)
else:
    bpy.ops.object.select_all(action='DESELECT')
    mesh=bpy.data.meshes.new('Lighting AO receiver')
    # The 45 mm planks are centred at -15 mm: their top is +7.5 mm. Bake above
    # that surface, never inside it (which would make every plank fully occluded).
    mesh.from_pydata([(-10,-8.5,.012),(10,-8.5,.012),(10,10.5,.012),(-10,10.5,.012)],[],[(0,1,2,3)])
    mesh.uv_layers.new(name='AO world UV')
    for loop in mesh.loops:
        v=mesh.vertices[loop.vertex_index].co
        mesh.uv_layers.active.data[loop.index].uv=((v.x+10)/20,(v.y+8.5)/19)
    target=bpy.data.objects.new('Lighting AO receiver',mesh);scene.collection.objects.link(target)
    material=bpy.data.materials.new('Lighting AO bake only');material.use_nodes=True
    nodes=material.node_tree.nodes;nodes.clear();links=material.node_tree.links
    ao=nodes.new('ShaderNodeAmbientOcclusion');ao.inputs['Distance'].default_value=.72;ao.samples=16
    emission=nodes.new('ShaderNodeEmission');surface=nodes.new('ShaderNodeOutputMaterial')
    links.new(ao.outputs['Color'],emission.inputs['Color']);links.new(emission.outputs[0],surface.inputs['Surface'])
    image=bpy.data.images.new('Library ground contact AO',width=2048,height=2048,alpha=False)
    image.colorspace_settings.name='Non-Color'
    texture=nodes.new('ShaderNodeTexImage');texture.image=image;nodes.active=texture
    target.data.materials.append(material);target.select_set(True);bpy.context.view_layer.objects.active=target
    scene.render.bake.margin=2;scene.cycles.samples=1
    bpy.ops.object.bake(type='EMIT')
    import numpy as np
    pixels=np.empty(2048*2048*4,dtype=np.float32);image.pixels.foreach_get(pixels)
    assert float(pixels.reshape(-1,4)[:,0].mean())>.65,'AO receiver is occluded by the floor itself'
    image.filepath_raw=str(output/'library-contact-ao.png');image.file_format='PNG';image.save()
    bpy.data.objects.remove(target,do_unlink=True)
    assert snapshot=={o.name:(tuple(v for row in o.matrix_world for v in row),len(o.data.vertices),len(o.data.polygons))
                      for o in scene.objects if o.type=='MESH'},'Unrelated geometry changed during lighting bake'
    config=json.loads((ROOT/'public/models/lighting-rig.json').read_text(encoding='utf-8'))
    for obj in list(scene.objects):
        if obj.type=='LIGHT':bpy.data.objects.remove(obj,do_unlink=True)
    def light(name,kind,location,energy,color,target):
        data=bpy.data.lights.new(name,kind);data.energy=energy;data.color=color
        obj=bpy.data.objects.new(name,data);scene.collection.objects.link(obj)
        obj.location=(location[0],-location[2],location[1])
        aim=Vector((target[0],-target[2],target[1]))
        obj.rotation_euler=(aim-obj.location).to_track_quat('-Z','Y').to_euler()
        return data
    sun=light('Window sun reference','SUN',config['sun']['position'],2.4,(1,.89,.72),config['sun']['target']);sun.angle=.06
    for index,p in enumerate(config['pendants']):
        data=light(f'Pendant reference {index}','AREA',p,38,(1,.73,.44),(p[0],0,p[2]))
        data.shape='RECTANGLE';data.size=.075;data.size_y=1.3
    scene.world.use_nodes=True
    scene.world.node_tree.nodes.get('Background').inputs[0].default_value=(.65,.76,1,1)
    scene.world.node_tree.nodes.get('Background').inputs[1].default_value=.3
    scene.cycles.samples=32
    scene.render.filepath=str(WORK/'blender-daylight-reference.png')
    bpy.ops.render.render(write_still=True)
    (WORK/'lighting-bake.json').write_text(json.dumps(dict(geometry_unchanged=True,resolution=2048,ao_distance_m=.72)),encoding='utf-8')
print('Read-only Blender lighting inspection complete; source scene was not saved')
