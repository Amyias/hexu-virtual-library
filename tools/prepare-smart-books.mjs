import fs from 'node:fs';
import {books as previous} from '../src/data/catalog.js';
import demoShelfMap from '../blender/demo-shelf-map.json' with {type:'json'};
const names=['计算机与AI技术','文学与历史哲学','商业经济与管理','艺术设计与建筑','科幻与未来馆藏'];
const colors=['#466b60','#7f6650','#536c7d','#886554','#596879'];
// Each face is a bookcase with a 300 mm deep cavity and a solid back panel whose inner face
// stands 200 mm from the shelf centre plane. A volume is shelved spine to the aisle, so it is
// its fore-edge that rests on that panel; the spine ends up at 200 mm + the volume's own depth.
// See blender/SHELVING_REFERENCES.md.
const BACK_PANEL_FACE=.20;
// The frame posts divide each face into four bays, and a row is packed along the spine — the
// thickness axis now, not the cover. That is what makes a real shelf: 1.85 m of bay holds
// roughly seventy 25 mm spines, not eight 216 mm covers.
const POSTS=[-8.75,-6.8,-4.8,-2.8,-0.85];
const POST=.10;
const CLEAR=.003;   // air at each end of a bay, so no volume touches a post
const BAYS=POSTS.length-1;
const BOARD_TOPS=[.09,.535,1.035,1.535];
const HEIGHT=.306;
const WIDTH=.216;
const DEPTH=.026;
// Every volume is the same size: 216 x 306 x 26 mm, the dimensions the template is authored
// at. An earlier pass varied width, height and thickness the way a stocked shelf does, but a
// library reads as a library precisely when its volumes are uniform — and a varied size also
// pushed the interactive book out of the reader's frame, hiding the cover.
const SIZE=1;
// Ten cloth shades per category. A real library orders its buckram from a finite range, and a
// continuous spread would make the .blend carry one material per volume.
const CLOTHS=10;
/** Deterministic 0..1 from a string: FNV-1a mixed so the low bits do not track the last
 *  character of a sequential id (unmixed, that turns a row into a regular staircase). */
function rand(seed){
  let hash=2166136261;
  for(let i=0;i<seed.length;i++)hash=Math.imul(hash^seed.charCodeAt(i),16777619);
  hash^=hash>>>15;hash=Math.imul(hash,2246822507);
  hash^=hash>>>13;hash=Math.imul(hash,3266489909);hash^=hash>>>16;
  return (hash>>>0)/4294967296;
}
const pick=(list,seed)=>list[Math.floor(rand(seed)*list.length)];
/** A run of 1-3 volumes that came as a set: one cloth, so identical volumes stand together. */
function runs(seed){
  const out=[];
  let index=0;
  while(true){
    const size=1+Math.floor(rand(`${seed}:set${index}`)*3);
    out.push({size,shade:Math.floor(rand(`${seed}:t${index}`)*CLOTHS)});
    index+=size;
    if(index>200)break;
  }
  return out;
}
/** One bay's row: identical spines shoulder to shoulder from the left frame post, with whatever
 *  is left over standing open at the end. Uniform volumes are what makes a library read as a
 *  library; only the cloth varies. */
function bayRow(seed,span){
  const thickness=DEPTH*SIZE;
  const count=Math.floor((span-CLEAR)/thickness);
  const shades=[];
  for(const run of runs(seed))for(let i=0;i<run.size;i++)shades.push(run.shade);
  return Array.from({length:count},(_,i)=>({thickness,centre:i*thickness+thickness/2,shade:shades[i%shades.length]}));
}
/** A book's cloth sits on its shelf's colour, one of ten shades, so a category reads as a
 *  family of related volumes rather than one dyed batch. */
function cloth(hex,shade){
  const step=shade/(CLOTHS-1);
  const [r,g,b]=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);
  const max=Math.max(r,g,b),min=Math.min(r,g,b),l=(max+min)/2;
  const s=max===min?0:(l>.5?(max-min)/(2-max-min):(max-min)/(max+min));
  let h=0;
  if(max!==min){
    if(max===r)h=((g-b)/(max-min)+(g<b?6:0))/6;
    else if(max===g)h=((b-r)/(max-min)+2)/6;
    else h=((r-g)/(max-min)+4)/6;
  }
  const light=Math.min(.86,Math.max(.14,l*(.82+step*.36)));
  const sat=Math.min(1,s*(0.94+step*0.12));
  const q=light<.5?light*(1+sat):light+sat-light*sat;
  const p=2*light-q;
  const channel=t=>t<0?t+1:t>1?t-1:t;
  const to=t=>Math.round(255*(t<1/6?p+(q-p)*6*t:t<1/2?q:t<2/3?p+(q-p)*(2/3-t)*6:p));
  return '#'+[h+1/3,h,h-1/3].map(t=>to(channel(t)).toString(16).padStart(2,'0')).join('');
}
// A named book keeps the face and the place in the bay recorded in blender/demo-shelf-map.json.
// That record is explicit rather than inferred from the previous catalogue's slot numbers: the
// bay capacity has changed twice, and inferring it moved books that should have stayed put.
const demos=new Map();
for(const b of previous.filter(b=>!b.placeholder))demos.set([b.shelf,b.side,b.layer].join(':'),b);
const rows=[];
for(let shelf=1;shelf<=5;shelf++)for(const side of ['A','B'])for(let layer=1;layer<=4;layer++)for(let bay=0;bay<BAYS;bay++){
  const row=bayRow(`S${shelf}${side}L${layer}B${bay}`,POSTS[bay+1]-POSTS[bay]-POST-CLEAR*2);
  const faceDemo=demos.get([shelf,side,layer].join(':'));
  const demoRow=faceDemo?demoShelfMap[faceDemo.title]:undefined;
  if(faceDemo&&!demoRow)throw new Error(`demo-shelf-map.json has no record for ${faceDemo.title}`);
  let demoPlace=-1;
  if(demoRow&&demoRow.shelf===shelf&&demoRow.side===side&&demoRow.layer===layer&&demoRow.bay===bay)demoPlace=Math.round(demoRow.fraction*(row.length-1));
  for(let place=0;place<row.length;place++){
    const slot=rows.filter(b=>b.shelf===shelf&&b.side===side&&b.layer===layer).length+1;
    const bookId=`HX-${String(rows.length+1).padStart(5,'0')}`;
    const locationCode=`S${shelf}-${side}-L${layer}-P${String(slot).padStart(3,'0')}`;
    const size=row[place];
    const demo=place===demoPlace?faceDemo:undefined;
    // A named book's recorded ids and position code are dropped rather than kept as aliases:
    // those numbers now name other volumes, and one search key must not point at two books.
    const aliases=(demo?.keys??[]).filter(k=>!/^(HX-?\d{4,5}|S\d-[AB]-L\d-P\d{2,3})$/.test(k));
    rows.push({title:demo?.title??`馆藏 ${bookId}`,author:demo?.author??'和序图书馆 · 编号样书',category:demo?.category??names[shelf-1],shelf,side,layer,slot,color:cloth(colors[shelf-1],size.shade),keys:[...new Set([...aliases,bookId,bookId.replace('-',''),locationCode])],synopsis:demo?.synopsis??'这是一册用于展示智能馆藏管理的编号样书。封面内嵌微型定位芯片，芯片编号与本书编号一一对应，内部标记记录书架、面向、层号和槽位。你可以查看芯片信息，核对当前存放位置，并体验取书、翻阅和归还的完整流程。',bookId,chipId:bookId,locationCode,placeholder:!demo,widthScale:SIZE,heightScale:SIZE,depthScale:SIZE,worldPosition:[(shelf-3)*3+(side==='A'?1:-1)*(BACK_PANEL_FACE+WIDTH*SIZE/2),+(BOARD_TOPS[layer-1]+HEIGHT*SIZE/2).toFixed(6),+(POSTS[bay]+POST/2+CLEAR+size.centre).toFixed(6)],chipPayload:{book_id:bookId,shelf_id:`Shelf_${shelf}`,shelf_side:side,layer,slot,location_code:locationCode}});
  }
}
/** A row is packed, so the checks below are about touching and about the shelf's own limits,
 *  not about even spacing. The count per bay is whatever the drawn spine widths come to. */
const faceHalfThickness=b=>b.depthScale*DEPTH/2;
for(let shelf=1;shelf<=5;shelf++)for(const side of ['A','B'])for(let layer=1;layer<=4;layer++)for(let bay=0;bay<BAYS;bay++){
  const row=rows.filter(b=>b.shelf===shelf&&b.side===side&&b.layer===layer&&Math.abs(b.worldPosition[2]-(POSTS[bay]+POSTS[bay+1])/2)<(POSTS[bay+1]-POSTS[bay])/2).sort((a,b)=>a.slot-b.slot);
  const span=POSTS[bay+1]-POSTS[bay]-POST-CLEAR*2;
  if(row.length<40)throw new Error(`Bay S${shelf}${side}L${layer}B${bay} holds only ${row.length} volumes`);
  const used=row.reduce((sum,b)=>sum+faceHalfThickness(b)*2,0);
  if(used>span+1e-6)throw new Error(`Bay S${shelf}${side}L${layer}B${bay} overflows by ${(used-span).toFixed(4)} m`);
  if(used<span*.9)throw new Error(`Bay S${shelf}${side}L${layer}B${bay} only ${(used/span*100).toFixed(1)}% full`);
  let edge=POSTS[bay]+POST/2+CLEAR;
  for(const b of row){
    if(Math.abs(b.worldPosition[2]-(edge+faceHalfThickness(b)))>5e-4)throw new Error(`${b.bookId} is not packed against its neighbour`);
    edge+=faceHalfThickness(b)*2;
  }
}
const demoRecords=Object.entries(demoShelfMap).filter(([title])=>!title.startsWith('_'));
if(rows.filter(b=>!b.placeholder).length!==demoRecords.length)throw new Error('Demo catalogue mapping lost books');
for(const b of rows){
  // Every volume is the template's own size. A varied shelf was tried and rejected: a library
  // reads as a library when its volumes match, and a wider volume also pushed the interactive
  // book out of the reader's frame, hiding its cover.
  if(b.widthScale!==SIZE||b.heightScale!==SIZE||b.depthScale!==SIZE)throw new Error(`${b.bookId} is not the standard size`);
  if(BACK_PANEL_FACE+WIDTH*SIZE>0.4955-0.002)throw new Error(`${b.bookId} reaches past the brass lip`);
}
fs.writeFileSync('blender/catalog.json',JSON.stringify(rows,null,2));
fs.writeFileSync('public/models/book-inventory.json',JSON.stringify(rows,null,2));
fs.writeFileSync('src/data/catalog.js','// Generated inventory: 5 shelves × 2 faces × 4 layers × 4 bays, packed spine-out.\nexport const books = '+JSON.stringify(rows,null,2)+';\nexport const anchors=[-6,-3,0,3,6];\nexport const heights=[.3,.7,1.2,1.7];\n');
console.log(`Prepared ${rows.length} unique chips and ${rows.filter(b=>!b.placeholder).length} named demo books.`);
