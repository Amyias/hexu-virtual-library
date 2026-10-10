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
  // The template's local Y is the book's height (216 mm wide, 306 mm tall, 26 mm deep), so
  // scaling that one axis varies how tall a volume stands without touching its width — the
  // chip engraving is a flat quad on the cover, and a width scale would smear it. The pose
  // origin is the book's centre, which the catalogue places at board top + half its height,
  // so a scaled book still lands squarely on the board.
  const poses=books.map(b=>new THREE.Matrix4().compose(new THREE.Vector3(...b.worldPosition),new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),b.side==='A'?Math.PI/2:-Math.PI/2),new THREE.Vector3(1,b.heightScale??1,1)));
  const pools=[];
  template.traverse(part=>{
    if(!part.isMesh)return;
    const material=part.material.clone();
    const cover=/FrontCover|RearBoard|RoundedSpine/.test(part.name);
    if(cover)material.color.set('white');
    // Volumes stand inside a bookcase, so the shelf and the board above already cast every
    // shadow a reader can see; a book's own cast shadow falls on the board it stands on and is
    // hidden by the book itself. Dropping it from the shadow pass matters at this scale: 1280
    // volumes across 44 mesh parts were 55k extra instances re-submitted every frame, and
    // removing it took the reference machine from 30.6 to 46.6 fps at a full shelf.
    const pool=new THREE.InstancedMesh(part.geometry,material,books.length);
    pool.name='SmartBookInstances_'+part.name;pool.castShadow=false;pool.receiveShadow=true;pool.frustumCulled=false;
    for(let i=0;i<books.length;i++){
      pool.setMatrixAt(i,poses[i].clone().multiply(part.matrixWorld));
      if(cover)pool.setColorAt(i,new THREE.Color(books[i].color));
    }
    scene.add(pool);pools.push({pool,local:part.matrixWorld.clone()});
  });
  // One 4096x2560 sheet carries every shelf engraving: 1280 books fit it as 32 columns by 40
  // rows, a 128x64 cell each. The chip close-up does not read this sheet (src/reader draws its
  // own 768x384 plate per book), so this only has to stay legible from shelf distance.
  const ATLAS_COLS=32,ATLAS_ROWS=40;
  const canvas=document.createElement('canvas');canvas.width=4096;canvas.height=2560;
  const cell=[canvas.width/ATLAS_COLS,canvas.height/ATLAS_ROWS];
  const ctx=canvas.getContext('2d');books.forEach((b,i)=>paintChip(ctx,b,(i%ATLAS_COLS)*cell[0],Math.floor(i/ATLAS_COLS)*cell[1],cell[0],cell[1]));
  const atlas=new THREE.CanvasTexture(canvas);atlas.colorSpace=THREE.SRGBColorSpace;
  const geometry=new THREE.PlaneGeometry(.028,.014);
  const offsets=new Float32Array(books.length*2);
  books.forEach((b,i)=>{offsets[i*2]=(i%ATLAS_COLS)/ATLAS_COLS;offsets[i*2+1]=1-(Math.floor(i/ATLAS_COLS)+1)/ATLAS_ROWS;b.origin=new THREE.Vector3(...b.worldPosition);b.instanceIndex=i;});
  geometry.setAttribute('atlasOffset',new THREE.InstancedBufferAttribute(offsets,2));
  const material=new THREE.MeshBasicMaterial({map:atlas,toneMapped:false});
  material.onBeforeCompile=shader=>{
    shader.vertexShader='attribute vec2 atlasOffset;\n'+shader.vertexShader;
    shader.vertexShader=shader.vertexShader.replace('#include <uv_vertex>',`#include <uv_vertex>\nvMapUv = vMapUv * vec2(1.0/${ATLAS_COLS}.0,1.0/${ATLAS_ROWS}.0) + atlasOffset;`);
  };
  material.customProgramCacheKey=()=> 'smart-chip-atlas-v2';
  const labels=new THREE.InstancedMesh(geometry,material,books.length);labels.name='UniqueChipEngravings';labels.frustumCulled=false;
  const local=new THREE.Matrix4().makeTranslation(.065,-.105,.01195);
  poses.forEach((pose,i)=>labels.setMatrixAt(i,pose.clone().multiply(local)));scene.add(labels);pools.push({pool:labels,local});
  const zero=new THREE.Matrix4().makeScale(0,0,0);
  const highlight=new THREE.BoxHelper(new THREE.Mesh(new THREE.BoxGeometry(.23,.32,.035)),0xbdecc5);
  highlight.visible=false;scene.add(highlight);
  return {
    setVisible(b,visible){for(const {pool,local} of pools){pool.setMatrixAt(b.instanceIndex,visible?poses[b.instanceIndex].clone().multiply(local):zero);pool.instanceMatrix.needsUpdate=true;}},
    highlight(b,on){highlight.visible=on;highlight.position.copy(b.origin);highlight.rotation.y=b.side==='A'?Math.PI/2:-Math.PI/2;highlight.scale.set(1,b.heightScale??1,1);},
    instancePools:pools.length,
  };
}
