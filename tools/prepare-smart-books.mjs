import fs from 'node:fs';
import {books as previous} from '../src/data/catalog.js';
const originals=previous.filter(b=>!b.placeholder);
const names=['计算机与AI技术','文学与历史哲学','商业经济与管理','艺术设计与建筑','科幻与未来馆藏'];
const colors=['#466b60','#7f6650','#536c7d','#886554','#596879'];
// Each face is a bookcase with a 300 mm deep cavity. Its solid back panel spans 170..200 mm
// from the shelf centre plane, so the face a book leans on is at 200 mm — measured to the
// side the book actually touches, not the side facing the central void. A book stands on the
// board and leans back, so its rear board must touch that face. 12.6 mm is the
// root-to-rear-board distance measured off smart-book.glb — re-measure it if the book
// template changes. See blender/SHELVING_REFERENCES.md.
const BACK_PANEL_FACE=.20;
const REAR_BOARD=.0126;
const REST_X=BACK_PANEL_FACE+REAR_BOARD;
// The frame posts divide each face into four bays. 100 mm of post and 216 mm of book leave
// room for eight books in both the 1.95 m and the 2.0 m bays; a ninth would overlap the
// brass frame, which tests/library.test.mjs rejects. Earlier versions placed two books per
// bay, so every shelf stood more than two thirds empty.
const POSTS=[-8.75,-6.8,-4.8,-2.8,-0.85];
const POST=.10;
const WIDTH=.216;
const CLEAR=.004;   // air at each end of a bay, so no volume touches a post
const PER_BAY=8;
const BOARD_TOPS=[.09,.535,1.035,1.535];
const HEIGHT=.306;
// Height varies per book, the way a real shelf does. 1280 identical volumes read as a
// texture; uneven tops are what make the row read as shelving. Deterministic from the book
// id, so re-running this generator reproduces the same wall byte for byte.
const heights=id=>{
  let hash=2166136261;                                  // FNV-1a
  for(let i=0;i<id.length;i++)hash=Math.imul(hash^id.charCodeAt(i),16777619);
  // Without this finalizer the low bits track the last digit of a sequential id, and the wall
  // comes out as a regular staircase instead of a shelf. Mixing them is the whole point.
  hash^=hash>>>15;hash=Math.imul(hash,2246822507);
  hash^=hash>>>13;hash=Math.imul(hash,3266489909);hash^=hash>>>16;
  return .92+((hash>>>0)%15)/100;                        // 0.92 .. 1.06 of the template
};
// A named book keeps the face recorded in the current catalogue, so re-running this
// generator never renumbers one. Slots are bay-major, so dividing the file's slot range by
// its four bays gives how many books each bay held: 2 in the catalogue this change replaces,
// 8 now. Reading a slot as "which bay, and where in it" makes one rule serve both grids, and
// leaves an already-migrated book exactly where it stands.
const demos=new Map();
for(const b of originals)demos.set([b.shelf,b.side,b.layer].join(':'),b);
const BAYS=POSTS.length-1;
const recordedPerBay=Math.max(...previous.map(b=>b.slot))/BAYS;
if(!Number.isInteger(recordedPerBay)||recordedPerBay<1)throw new Error('Unreadable slot grid in the current catalogue');
const remap=demo=>(Math.ceil(demo.slot/recordedPerBay)-1)*PER_BAY+((demo.slot-1)%recordedPerBay)+1;
/** Even spacing inside one bay: the ends are inset half a post, half a book and 4 mm of air,
 *  and the leftover slack is shared out over the seven gaps, so the row is centred in its bay
 *  and no book touches a post. */
function baySlots(from,to){
  const first=from+POST/2+WIDTH/2+CLEAR;
  const last=to-POST/2-WIDTH/2-CLEAR;
  const step=(last-first)/(PER_BAY-1);
  return Array.from({length:PER_BAY},(_,i)=>first+i*step);
}
const zSlots=[];
for(let bay=0;bay<POSTS.length-1;bay++)zSlots.push(...baySlots(POSTS[bay],POSTS[bay+1]));
const rows=[];
for(let shelf=1;shelf<=5;shelf++)for(const side of ['A','B'])for(let layer=1;layer<=4;layer++)for(let slot=1;slot<=PER_BAY*4;slot++){
  const bookId=`HX-${String(rows.length+1).padStart(4,'0')}`;
  const locationCode=`S${shelf}-${side}-L${layer}-P${String(slot).padStart(2,'0')}`;
  const faceDemo=demos.get([shelf,side,layer].join(':'));
  const demo=faceDemo&&remap(faceDemo)===slot?faceDemo:undefined;
  const scale=heights(bookId);
  // A named book's recorded ids and position code are dropped rather than kept as aliases:
  // those numbers now name other books, and one search key must not point at two volumes.
  const aliases=(demo?.keys??[]).filter(k=>!/^(HX-?\d{4}|S\d-[AB]-L\d-P\d\d)$/.test(k));
  rows.push({title:demo?.title??`馆藏 ${bookId}`,author:demo?.author??'和序图书馆 · 编号样书',category:demo?.category??names[shelf-1],shelf,side,layer,slot,color:colors[shelf-1],keys:[...new Set([...aliases,bookId,bookId.replace('-',''),locationCode])],synopsis:demo?.synopsis??'这是一册用于展示智能馆藏管理的编号样书。封面内嵌微型定位芯片，芯片编号与本书编号一一对应，内部标记记录书架、面向、层号和槽位。你可以查看芯片信息，核对当前存放位置，并体验取书、翻阅和归还的完整流程。',bookId,chipId:bookId,locationCode,placeholder:!demo,heightScale:+scale.toFixed(3),worldPosition:[(shelf-3)*3+(side==='A'?REST_X:-REST_X),+(BOARD_TOPS[layer-1]+HEIGHT*scale/2).toFixed(6),+zSlots[slot-1].toFixed(6)],chipPayload:{book_id:bookId,shelf_id:`Shelf_${shelf}`,shelf_side:side,layer,slot,location_code:locationCode}});
}
// Self-checks: the named books must all survive, no book may touch a frame post, and the row
// spacing must stay distinct. Each of these has silently broken a rebuild before.
if(rows.filter(b=>!b.placeholder).length!==12)throw new Error('Demo catalogue mapping lost books');
for(const b of rows)for(const post of POSTS)
  if(Math.abs(b.worldPosition[2]-post)<=POST/2+WIDTH/2)throw new Error(`${b.bookId} overlaps the post at ${post}`);
if(new Set(zSlots.map(z=>z.toFixed(6))).size!==zSlots.length)throw new Error('Bay spacing collapsed');
if(zSlots.length!==PER_BAY*(POSTS.length-1))throw new Error('Wrong number of bay slots');
fs.writeFileSync('blender/catalog.json',JSON.stringify(rows,null,2));
fs.writeFileSync('public/models/book-inventory.json',JSON.stringify(rows,null,2));
fs.writeFileSync('src/data/catalog.js','// Generated inventory: 5 shelves × 2 faces × 4 layers × 4 bays × 8 books.\nexport const books = '+JSON.stringify(rows,null,2)+';\nexport const anchors=[-6,-3,0,3,6];\nexport const heights=[.3,.7,1.2,1.7];\n');
console.log(`Prepared ${rows.length} unique chips and ${rows.filter(b=>!b.placeholder).length} named demo books.`);
