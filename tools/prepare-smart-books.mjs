import fs from 'node:fs';
import {books as previous} from '../src/data/catalog.js';
const originals=previous.filter(b=>!b.placeholder);
const names=['计算机与AI技术','文学与历史哲学','商业经济与管理','艺术设计与建筑','科幻与未来馆藏'];
const colors=['#466b60','#7f6650','#536c7d','#886554','#596879'];
const rows=[];
for(let shelf=1;shelf<=5;shelf++)for(const side of ['A','B'])for(let layer=1;layer<=4;layer++)for(let slot=1;slot<=8;slot++){
  const bookId=`HX-${String(rows.length+1).padStart(4,'0')}`;
  const locationCode=`S${shelf}-${side}-L${layer}-P${String(slot).padStart(2,'0')}`;
  const demo=originals.find((b,i)=>b.shelf===shelf&&b.side===side&&b.layer===layer&&slot===8-i%2);
  rows.push({title:demo?.title??`馆藏 ${bookId}`,author:demo?.author??'和序图书馆 · 编号样书',category:demo?.category??names[shelf-1],shelf,side,layer,slot,color:colors[shelf-1],keys:[...(demo?.keys??[]),bookId,bookId.replace('-',''),locationCode],synopsis:demo?.synopsis??'这是一册用于展示智能馆藏管理的编号样书。封面内嵌微型定位芯片，芯片编号与本书编号一一对应，内部标记记录书架、面向、层号和槽位。你可以查看芯片信息，核对当前存放位置，并体验取书、翻阅和归还的完整流程。',bookId,chipId:bookId,locationCode,placeholder:!demo,worldPosition:[(shelf-3)*3+(side==='A'?.46:-.46),[.243,.688,1.188,1.688][layer-1],[-8.2,-7.4,-6.2,-5.4,-4.2,-3.4,-2.2,-1.4][slot-1]],chipPayload:{book_id:bookId,shelf_id:`Shelf_${shelf}`,shelf_side:side,layer,slot,location_code:locationCode}});
}
if(rows.filter(b=>!b.placeholder).length!==12)throw new Error('Demo catalogue mapping lost books');
fs.writeFileSync('blender/catalog.json',JSON.stringify(rows,null,2));
fs.writeFileSync('public/models/book-inventory.json',JSON.stringify(rows,null,2));
fs.writeFileSync('src/data/catalog.js','// Generated inventory: 5 shelves × 2 faces × 4 layers × 8 slots.\nexport const books = '+JSON.stringify(rows,null,2)+';\nexport const anchors=[-6,-3,0,3,6];\nexport const heights=[.3,.7,1.2,1.7];\n');
console.log(`Prepared ${rows.length} unique chips and ${rows.filter(b=>!b.placeholder).length} named demo books.`);
