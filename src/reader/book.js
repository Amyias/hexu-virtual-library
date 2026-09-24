import * as THREE from "three";
import { chipTexture } from '../scene/smart-books.js';
/** Dynamic text textures and a true spine hinge for the interactive reading copy. */
export function createBookFactory(renderer,template) {
  const mat = (color) =>
    new THREE.MeshStandardMaterial({ color, roughness: 0.65 });
  const boxGeo = new THREE.BoxGeometry(1, 1, 1);
  function box(w, h, d, material, x, y, z, parent) {
    const m = new THREE.Mesh(boxGeo, material);
    m.scale.set(w, h, d);
    m.position.set(x, y, z);
    parent.add(m);
    return m;
  }
  function texture(canvas) {
    const t = new THREE.CanvasTexture(canvas);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
    return t;
  }
  function wrap(ctx, text, x, y, maxWidth, lineHeight) {
    let line = "";
    for (const ch of text) {
      if (ctx.measureText(line + ch).width > maxWidth && line) {
        ctx.fillText(line, x, y);
        line = ch;
        y += lineHeight;
      } else line += ch;
    }
    if (line) ctx.fillText(line, x, y);
    return y + lineHeight;
  }
  function pageTexture(b, cover = false) {
    const c = document.createElement("canvas");
    c.width = 1000;
    c.height = 1400;
    const ctx = c.getContext("2d");
    ctx.fillStyle = cover ? b.color : "#faf7ee";
    ctx.fillRect(0, 0, 1000, 1400);
    ctx.strokeStyle = cover ? "#ecdfb475" : "#9caa8e";
    ctx.lineWidth = 2;
    ctx.strokeRect(58, 58, 884, 1284);
    ctx.textAlign = "left";
    ctx.fillStyle = cover ? "#f1e8cb" : "#607458";
    ctx.font = "22px sans-serif";
    ctx.fillText(
      cover
        ? "H E  X U   /   C O L L E C T I O N"
        : "H E  X U   /   阅 读 档 案",
      95,
      133,
    );
    ctx.font = '66px "Microsoft YaHei",sans-serif';
    ctx.fillStyle = cover ? "#fff7e1" : "#284d3c";
    const y = wrap(ctx, b.title, 95, cover ? 330 : 240, 810, 87);
    ctx.font = '32px "Microsoft YaHei",sans-serif';
    ctx.fillStyle = cover ? "#e0ddc9" : "#596650";
    const authorY = wrap(ctx, b.author, 95, y + 30, 810, 43);
    if (cover) {
      ctx.strokeStyle = "#d6d6b780";
      for (let i = 0; i < 14; i++) {
        ctx.beginPath();
        ctx.ellipse(
          510,
          870,
          170 + i * 12,
          170 + i * 8,
          i * 0.1,
          0,
          Math.PI * 2,
        );
        ctx.stroke();
      }
      ctx.font = "26px sans-serif";
      ctx.fillText("把好奇，翻成下一页。", 95, 1245);
    } else {
      ctx.fillStyle = "#849174";
      ctx.fillRect(95, authorY + 25, 75, 3);
      ctx.font = '40px "Microsoft YaHei",sans-serif';
      ctx.fillStyle = "#263e32";
      wrap(ctx, b.synopsis, 95, authorY + 95, 810, 66);
      ctx.fillStyle = "#62745a";
      ctx.font = "26px sans-serif";
      ctx.fillText(b.category, 95, 1165);
      ctx.fillText(
        `馆藏 0${b.shelf} · ${b.side} 面 · 第 ${b.layer} 层`,
        95,
        1215,
      );
      ctx.fillText("01                                   和序图书馆", 95, 1300);
    }
    return texture(c);
  }
  function createBook(b) {
    const root = new THREE.Group();
    const body=cloneTemplate(b);body.scale.setScalar(1/.15);root.add(body);
    const hinge=body.getObjectByName('FrontHinge');
    if(!hinge)throw new Error('Blender book hinge missing');
    const coverMesh=body.getObjectByName('FrontCover_top');
    const page=plane(.204,.29,pageTexture(b));page.position.set(0,0,.0084);body.add(page);
    const c=document.createElement('canvas');c.width=900;c.height=1100;const ctx=c.getContext('2d');
    ctx.fillStyle='#e7dec1';ctx.font='22px sans-serif';ctx.fillText('HE XU / SMART COLLECTION',55,80);
    ctx.font='64px "Microsoft YaHei",sans-serif';const y=wrap(ctx,b.title,55,220,790,90);
    ctx.font='28px "Microsoft YaHei",sans-serif';wrap(ctx,b.author,55,y+70,790,44);
    ctx.strokeStyle='#d8c696';ctx.lineWidth=2;ctx.strokeRect(22,22,856,1056);
    ctx.font='30px monospace';ctx.fillText(b.bookId,55,970);
    const ink=plane(.198,.197,texture(c));ink.material.transparent=true;ink.position.set(.108,.045,.0023);hinge.add(ink);
    const label=plane(.028,.014,chipTexture(b));label.position.set(.173,-.105,.00095);hinge.add(label);
    return { root, hinge, coverMesh };
  }

  function cloneTemplate(b){
    const body=template.clone(true);
    body.traverse(o=>{if(o.isMesh){o.material=o.material.clone();if(/FrontCover|RearBoard|RoundedSpine/.test(o.name))o.material.color.set(b.color);}});
    return body;
  }
  function plane(w,h,map){
    const mesh=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map,toneMapped:false}));
    mesh.userData.ownedGeometry=true;mesh.material.userData.ownedMap=true;return mesh;
  }
  function createChip(b){
    const root=new THREE.Group(),parts=new THREE.Group();root.add(parts);parts.scale.setScalar(45);
    const copy=cloneTemplate(b);const hinge=copy.getObjectByName('FrontHinge');
    for(const child of [...hinge.children])if(/Chip|Recess/.test(child.name)){hinge.remove(child);child.position.x-=.173;child.position.y+=.105;parts.add(child);}
    dispose(copy);
    const label=plane(.028,.014,chipTexture(b));label.position.z=.00095;parts.add(label);
    return root;
  }

  function dispose(root) {
    root.traverse((o) => {
      if (o.isMesh) {
        if (o.userData.ownedGeometry) o.geometry.dispose();
        for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
          if(m.userData.ownedMap)m.map?.dispose();
          m.dispose();
        }
      }
    });
    root.removeFromParent();
  }
  return { create: createBook,createChip, dispose };
}
