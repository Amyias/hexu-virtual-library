import * as THREE from 'three';

export function paintChip(ctx,b,x,y,w,h){
  ctx.fillStyle='#10231f';ctx.fillRect(x,y,w,h);
  ctx.textAlign='center';ctx.fillStyle='#e7e3bd';
  ctx.font=`600 ${h*.27}px monospace`;ctx.fillText(b.chipId,x+w/2,y+h*.43);
  ctx.fillStyle='#acc6ab';ctx.font=`${h*.19}px monospace`;ctx.fillText(b.locationCode,x+w/2,y+h*.77);
}
export function chipTexture(b){
  const c=document.createElement('canvas');c.width=768;c.height=384;
  paintChip(c.getContext('2d'),b,0,0,c.width,c.height);
  const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return t;
}

/** Every visible book uses the same Blender geometry, batched with GPU instancing. */
export function createShelfBooks(scene,template,books){
  template.updateMatrixWorld(true);
  const poses=books.map(b=>new THREE.Matrix4().compose(new THREE.Vector3(...b.worldPosition),new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),b.side==='A'?Math.PI/2:-Math.PI/2),new THREE.Vector3(1,1,1)));
  const pools=[];
  template.traverse(part=>{
    if(!part.isMesh)return;
    const material=part.material.clone();
    const cover=/FrontCover|RearBoard|RoundedSpine/.test(part.name);
    if(cover)material.color.set('white');
    const pool=new THREE.InstancedMesh(part.geometry,material,books.length);
    pool.name='SmartBookInstances_'+part.name;pool.castShadow=!part.name.includes('Window');pool.receiveShadow=true;pool.frustumCulled=false;
    for(let i=0;i<books.length;i++){
      pool.setMatrixAt(i,poses[i].clone().multiply(part.matrixWorld));
      if(cover)pool.setColorAt(i,new THREE.Color(books[i].color));
    }
    scene.add(pool);pools.push({pool,local:part.matrixWorld.clone()});
  });
  const canvas=document.createElement('canvas');canvas.width=4096;canvas.height=2560;
  const ctx=canvas.getContext('2d');books.forEach((b,i)=>paintChip(ctx,b,(i%16)*256,Math.floor(i/16)*128,256,128));
  const atlas=new THREE.CanvasTexture(canvas);atlas.colorSpace=THREE.SRGBColorSpace;
  const geometry=new THREE.PlaneGeometry(.028,.014);
  const offsets=new Float32Array(books.length*2);
  books.forEach((b,i)=>{offsets[i*2]=(i%16)/16;offsets[i*2+1]=1-(Math.floor(i/16)+1)/20;b.origin=new THREE.Vector3(...b.worldPosition);b.instanceIndex=i;});
  geometry.setAttribute('atlasOffset',new THREE.InstancedBufferAttribute(offsets,2));
  const material=new THREE.MeshBasicMaterial({map:atlas,toneMapped:false});
  material.onBeforeCompile=shader=>{
    shader.vertexShader='attribute vec2 atlasOffset;\n'+shader.vertexShader;
    shader.vertexShader=shader.vertexShader.replace('#include <uv_vertex>','#include <uv_vertex>\nvMapUv = vMapUv * vec2(0.0625,0.05) + atlasOffset;');
  };
  material.customProgramCacheKey=()=> 'smart-chip-atlas-v1';
  const labels=new THREE.InstancedMesh(geometry,material,books.length);labels.name='UniqueChipEngravings';labels.frustumCulled=false;
  const local=new THREE.Matrix4().makeTranslation(.065,-.105,.01195);
  poses.forEach((pose,i)=>labels.setMatrixAt(i,pose.clone().multiply(local)));scene.add(labels);pools.push({pool:labels,local});
  const zero=new THREE.Matrix4().makeScale(0,0,0);
  const highlight=new THREE.BoxHelper(new THREE.Mesh(new THREE.BoxGeometry(.23,.32,.035)),0xbdecc5);
  highlight.visible=false;scene.add(highlight);
  return {
    setVisible(b,visible){for(const {pool,local} of pools){pool.setMatrixAt(b.instanceIndex,visible?poses[b.instanceIndex].clone().multiply(local):zero);pool.instanceMatrix.needsUpdate=true;}},
    highlight(b,on){highlight.visible=on;highlight.position.copy(b.origin);highlight.rotation.y=b.side==='A'?Math.PI/2:-Math.PI/2;},
    instancePools:pools.length,
  };
}
