import fs from 'node:fs';
import {books as previous} from '../src/data/catalog.js';
const originals=previous.filter(b=>!b.placeholder);
const names=['计算机与AI技术','文学与历史哲学','商业经济与管理','艺术设计与建筑','科幻与未来馆藏'];
const colors=['#466b60','#7f6650','#536c7d','#886554','#596879'];
// Each face is a bookcase with a 300 mm deep cavity. Its solid back panel spans 170..200 mm
// from the shelf centre plane, so the face a book leans on is at 200 mm — measured to the
// side the book actually touches, not the side facing the central void. A book stands on the
// board and leans back, so its rear board must touch that face: the root sits 12.6 mm of the
// volume's own thickness out from it, which is why a thicker volume also protrudes further
// into the aisle. 12.6 mm is the root-to-rear-board distance measured off smart-book.glb —
// re-measure it if the book template changes. See blender/SHELVING_REFERENCES.md.
const BACK_PANEL_FACE=.20;
const REAR_BOARD=.0126;
// The frame posts divide each face into four bays. The reference is a real bookcase: each bay
// holds eight volumes, and they stand shoulder to shoulder with the slack left at the end of
// the row. See blender/SHELVING_REFERENCES.md for the shelving rules this follows.
const POSTS=[-8.75,-6.8,-4.8,-2.8,-0.85];
const POST=.10;
const CLEAR=.004;   // air at each end of a bay, so no volume touches a post
const PER_BAY=8;
const BAYS=POSTS.length-1;
const BOARD_TOPS=[.09,.535,1.035,1.535];
const HEIGHT=.306;
const WIDTH=.216;
// Sizes vary per volume, the way a shelf of real books does: 170-300 mm of cover, 245-337 mm
// tall, 21-38 mm thick (the template is authored at 216 x 306 x 26 mm). A wall of identical
// slabs reads as a texture. Width is the axis the row packs along; height and thickness are
// how a volume stands and how far it leans into the aisle.
// The chip engraving is 28 x 14 mm on every cover and the pocket around it scales with the
// cover, so the narrowest row still has to hold it: 43 * 0.78 * 0.90 = 30 mm of recess for a
// 28 mm label. Do not widen this palette without shrinking the label in src/scene/smart-books.js.
const WIDTHS=[.78,.84,.90,.96,1.02,1.08,1.14];
const HEIGHTS=[.80,.85,.90,.95,1.00,1.05,1.10];
const DEPTHS=[.80,.90,1.00,1.15,1.30,1.48];
// Ten cloth shades per category. A real library orders its buckram from a finite range, and a
// continuous spread would make the .blend carry one material per volume — six hundred of them,
// which took a Blender rebuild from minutes to the better part of an hour.
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
/** A run of 1-3 volumes that came as a set: one size, one cloth colour. */
function runs(seed,count){
  const out=[];
  let index=0;
  while(index<count){
    const size=1+Math.floor(rand(`${seed}:set${index}`)*3);
    out.push({size:Math.min(size,count-index),width:pick(WIDTHS,`${seed}:w${index}`),height:pick(HEIGHTS,`${seed}:h${index}`),depth:pick(DEPTHS,`${seed}:d${index}`),shade:Math.floor(rand(`${seed}:t${index}`)*CLOTHS)});
    index+=out[out.length-1].size;
  }
  return out;
}
/** One bay's row: eight volumes shoulder to shoulder, the leftover width left standing at the
 *  end of the row. Widths are drawn from the palette and then scaled so the row exactly fills
 *  the bay: the spread is 1.46x at most, which keeps the widest folio near 300 mm and the
 *  narrowest cover wide enough for its chip pocket. */
function bayRow(seed,span){
  const slack=span*(.012+rand(`${seed}:slack`)*.018);
  const budget=span-slack;
  const books=[];
  for(const run of runs(seed,PER_BAY))for(let i=0;i<run.size;i++)books.push(run);
  const raw=books.reduce((sum,b)=>sum+b.width*WIDTH,0);
  const fit=budget/raw;
  let edge=0;
  return books.map(b=>{
    const width=b.width*WIDTH*fit;
    const centre=edge+width/2;
    edge+=width;
    return {width,centre,height:b.height,depth:b.depth,shade:b.shade};
  });
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
// A named book keeps the face recorded in the current catalogue, so re-running this generator
// never renumbers one. Its recorded slot is read as "which bay, and where in it", which makes
// one rule serve every bay capacity and leaves an already-placed book exactly where it stands.
const demos=new Map();
for(const b of originals)demos.set([b.shelf,b.side,b.layer].join(':'),b);
const recordedPerBay=Math.max(...previous.map(b=>b.slot))/BAYS;
if(!Number.isInteger(recordedPerBay)||recordedPerBay<1)throw new Error('Unreadable slot grid in the current catalogue');
const remap=demo=>(Math.ceil(demo.slot/recordedPerBay)-1)*PER_BAY+((demo.slot-1)%recordedPerBay)+1;
const rows=[];
for(let shelf=1;shelf<=5;shelf++)for(const side of ['A','B'])for(let layer=1;layer<=4;layer++)for(let slot=1;slot<=PER_BAY*BAYS;slot++){
  const bookId=`HX-${String(rows.length+1).padStart(4,'0')}`;
  const locationCode=`S${shelf}-${side}-L${layer}-P${String(slot).padStart(2,'0')}`;
  const bay=Math.floor((slot-1)/PER_BAY);
  const place=(slot-1)%PER_BAY;
  const row=bayRow(`S${shelf}${side}L${layer}B${bay}`,POSTS[bay+1]-POSTS[bay]-POST-CLEAR*2);
  const size=row[place];
  const faceDemo=demos.get([shelf,side,layer].join(':'));
  const demo=faceDemo&&remap(faceDemo)===slot?faceDemo:undefined;
  // A named book's recorded ids and position code are dropped rather than kept as aliases:
  // those numbers now name other books, and one search key must not point at two volumes.
  const aliases=(demo?.keys??[]).filter(k=>!/^(HX-?\d{4}|S\d-[AB]-L\d-P\d\d)$/.test(k));
  rows.push({title:demo?.title??`馆藏 ${bookId}`,author:demo?.author??'和序图书馆 · 编号样书',category:demo?.category??names[shelf-1],shelf,side,layer,slot,color:cloth(colors[shelf-1],size.shade),keys:[...new Set([...aliases,bookId,bookId.replace('-',''),locationCode])],synopsis:demo?.synopsis??'这是一册用于展示智能馆藏管理的编号样书。封面内嵌微型定位芯片，芯片编号与本书编号一一对应，内部标记记录书架、面向、层号和槽位。你可以查看芯片信息，核对当前存放位置，并体验取书、翻阅和归还的完整流程。',bookId,chipId:bookId,locationCode,placeholder:!demo,widthScale:+(size.width/WIDTH).toFixed(4),heightScale:size.height,depthScale:size.depth,worldPosition:[(shelf-3)*3+(side==='A'?1:-1)*(BACK_PANEL_FACE+REAR_BOARD*size.depth),+(BOARD_TOPS[layer-1]+HEIGHT*size.height/2).toFixed(6),+(POSTS[bay]+POST/2+CLEAR+size.centre).toFixed(6)],chipPayload:{book_id:bookId,shelf_id:`Shelf_${shelf}`,shelf_side:side,layer,slot,location_code:locationCode}});
}
/** The volumes stand shoulder to shoulder with one gap at the end of the row: the packing is
 *  the point of this change, so the checks below are about touching, not about spacing. */
const faceHalfWidth=b=>b.widthScale*WIDTH/2;
for(let shelf=1;shelf<=5;shelf++)for(const side of ['A','B'])for(let layer=1;layer<=4;layer++){
  for(let bay=0;bay<BAYS;bay++){
    const row=rows.filter(b=>b.shelf===shelf&&b.side===side&&b.layer===layer&&Math.floor((b.slot-1)/PER_BAY)===bay).sort((a,b)=>a.slot-b.slot);
    if(row.length!==PER_BAY)throw new Error(`Bay S${shelf}${side}L${layer}B${bay} holds ${row.length}`);
    const span=POSTS[bay+1]-POSTS[bay]-POST-CLEAR*2;
    const used=row.reduce((sum,b)=>sum+faceHalfWidth(b)*2,0);
    if(used>span+1e-6)throw new Error(`Bay S${shelf}${side}L${layer}B${bay} overflows by ${(used-span).toFixed(4)} m`);
    if(used<span*.80)throw new Error(`Bay S${shelf}${side}L${layer}B${bay} only ${(used/span*100).toFixed(1)}% full`);
    let edge=POSTS[bay]+POST/2+CLEAR;
    for(const b of row){
      // Half a millimetre of slack: the catalogue stores each width as a four-decimal ratio,
      // so a position recomputed from it can differ from the exact packing by a hair.
      if(Math.abs(b.worldPosition[2]-(edge+faceHalfWidth(b)))>5e-4)throw new Error(`${b.bookId} is not packed against its neighbour`);
      edge+=faceHalfWidth(b)*2;
    }
  }
}
const heights=[...new Set(rows.map(b=>b.heightScale))];
if(rows.length!==PER_BAY*BAYS*5*2*4)throw new Error('Wrong number of books');
if(rows.filter(b=>!b.placeholder).length!==12)throw new Error('Demo catalogue mapping lost books');
if(!heights.every(h=>h>=.80&&h<=1.10))throw new Error('Height palette out of range');
// The chip pocket is 43 mm wide on a 216 mm cover and the label is 28 mm, so a volume can
// only be so narrow; at the other end a 300 mm cover is already a folio.
for(const b of rows){
  const width=b.widthScale*WIDTH;
  if(width<.15||width>.30)throw new Error(`${b.bookId} is ${(width*1000).toFixed(0)} mm wide`);
  if(b.depthScale<.75||b.depthScale>1.55)throw new Error(`${b.bookId} has an out-of-range thickness`);
}
fs.writeFileSync('blender/catalog.json',JSON.stringify(rows,null,2));
fs.writeFileSync('public/models/book-inventory.json',JSON.stringify(rows,null,2));
fs.writeFileSync('src/data/catalog.js','// Generated inventory: 5 shelves × 2 faces × 4 layers × 4 bays × 8 books.\nexport const books = '+JSON.stringify(rows,null,2)+';\nexport const anchors=[-6,-3,0,3,6];\nexport const heights=[.3,.7,1.2,1.7];\n');
console.log(`Prepared ${rows.length} unique chips and ${rows.filter(b=>!b.placeholder).length} named demo books.`);
