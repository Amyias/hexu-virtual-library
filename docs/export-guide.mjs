import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { deflateRawSync } from 'node:zlib';

// Build-time dependency only. The exported HTML needs no JavaScript or CDN.
const require = createRequire(import.meta.url);
const { marked } = await import(pathToFileURL(require.resolve('marked')).href);
const docs = path.dirname(fileURLToPath(import.meta.url));
const output = path.join(docs, 'portable');
const names = ['architecture', 'voice-flow', 'asset-pipeline'];
const sourceBase = 'https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/';
await fs.mkdir(path.join(output, 'diagrams'), { recursive: true });

const source = (await fs.readFile(path.join(docs, 'TECHNICAL_GUIDE.md'), 'utf8'))
  .replace(/<!-- export-note:start -->[\s\S]*?<!-- export-note:end -->\s*/g, '')
  .replace(/\]\(\.\.\/([^\s)]+)\)/g, (_, relative) => `](${sourceBase}${relative})`);
const intro = '> 分享说明：Markdown 请与 diagrams/ 文件夹一起移动；单独移动文件请选 TECHNICAL_GUIDE.html。三张配图在 HTML 内嵌，可离线阅读；源码链接指向 Gitee，访问私有仓库需要联网并登录。\n\n';
const markdown = source.replace(/\n\n/, `\n\n${intro}`);
await fs.writeFile(path.join(output, 'TECHNICAL_GUIDE.md'), markdown);

const esc = value => value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
let body = marked.parse(markdown, { gfm: true });
for (const name of names) {
  const svg = await fs.readFile(path.join(docs, 'diagrams', `${name}.svg`), 'utf8');
  const png = await fs.readFile(path.join(docs, 'diagrams', `${name}.png`));
  await fs.writeFile(path.join(output, 'diagrams', `${name}.svg`), svg);
  await fs.writeFile(path.join(output, 'diagrams', `${name}.png`), png);
  // Namespacing prevents title, description and arrow IDs colliding across diagrams.
  const inline = svg.replace(/<\?xml[^>]*\?>\s*/g, '')
    .replace(/\bid="([^"]+)"/g, (_, id) => `id="${name}-${id}"`)
    .replace(/url\(#([^)]+)\)/g, (_, id) => `url(#${name}-${id})`)
    .replace(/aria-labelledby="([^"]+)"/g, (_, ids) => `aria-labelledby="${ids.split(/\s+/).map(id => `${name}-${id}`).join(' ')}"`);
  body = body.replace(new RegExp(`<img src="diagrams/${name}\\.png" alt="([^"]*)"[^>]*>`), (_, alt) =>
    `<figure class="diagram" id="figure-${name}">${inline}<figcaption>${alt}</figcaption></figure>`);
  body = body.replaceAll(`href="diagrams/${name}.svg"`, `href="data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}" download="${name}.svg"`)
    .replaceAll(`href="diagrams/${name}.png"`, `href="data:image/png;base64,${png.toString('base64')}" download="${name}.png"`);
}
const toc = [];
body = body.replace(/<h2>(.*?)<\/h2>/g, (_, title) => {
  const id = `section-${toc.length + 1}`;
  toc.push(`<a href="#${id}">${title}</a>`);
  return `<h2 id="${id}">${title}</h2>`;
});
// A diagram replacing a paragraph image must not leave invalid p/figure nesting.
body = body.replace(/<p>(<figure[\s\S]*?<\/figure>)<\/p>/g, '$1');
const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>和序 · 技术实现与系统架构</title>
<style>
:root{color-scheme:light;--ink:#233c35;--muted:#61716b;--line:#dce5df;--paper:#fffefa;--accent:#28604d}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:#edf1eb;color:var(--ink);font:16px/1.85 "Microsoft YaHei","PingFang SC",system-ui,sans-serif;overflow-wrap:anywhere}
.layout{max-width:1520px;margin:auto;display:grid;grid-template-columns:235px minmax(0,1fr);gap:28px;padding:32px}
nav{position:sticky;top:32px;align-self:start;max-height:calc(100vh - 64px);overflow:auto;font-size:13px;padding:18px 0}nav strong{display:block;font-size:18px;margin-bottom:14px}nav a{display:block;margin:8px 0;text-decoration:none;color:var(--muted)}nav a:hover{color:var(--accent)}
main{min-width:0;background:var(--paper);border:1px solid var(--line);border-radius:18px;padding:clamp(22px,4vw,56px);box-shadow:0 14px 48px #264c3610}
h1{font-size:clamp(26px,3vw,38px);line-height:1.4;margin:0 0 28px}h2{font-size:25px;margin:48px 0 18px;padding-top:14px;border-top:1px solid var(--line)}h3{font-size:19px;margin:28px 0 12px}a{color:var(--accent);text-underline-offset:3px}p{margin:14px 0}blockquote{margin:22px 0;padding:12px 20px;border-left:3px solid #699d84;background:#f1f6ef;color:var(--muted)}blockquote p{margin:4px 0}
table{width:100%;border-collapse:collapse;font-size:14px;margin:20px 0}th,td{border:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top}th{background:#eaf1e9}tr:nth-child(even){background:#f7f9f4}
code{font-family:Consolas,monospace;font-size:.9em;background:#edf2ed;padding:2px 5px;border-radius:4px}pre{overflow:auto;background:#18342b;color:#ecf4e9;padding:20px;border-radius:10px;line-height:1.65}pre code{background:none;color:inherit;padding:0}
.diagram{margin:24px 0;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#f7f8f1}.diagram svg{width:100%;height:auto;display:block}figcaption{font-size:13px;color:var(--muted);padding:8px 14px;text-align:center;border-top:1px solid var(--line)}li{margin:6px 0}img{max-width:100%}
footer{color:var(--muted);font-size:13px;margin-top:36px;padding-top:18px;border-top:1px solid var(--line)}
@media(max-width:960px){.layout{display:block;padding:16px}nav{position:static;max-height:none;padding:8px 8px 20px;display:flex;gap:8px 16px;flex-wrap:wrap}nav strong{width:100%;margin-bottom:0}nav a{margin:0}main{padding:22px}table{font-size:12px}th,td{padding:6px}h2{font-size:22px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{body{background:white;font-size:10pt}.layout{display:block;padding:0}nav{display:none}main{border:0;box-shadow:none;padding:0}h2,h3{break-after:avoid}.diagram,pre,tr{break-inside:avoid}pre{white-space:pre-wrap}a{color:inherit}.diagram{border-radius:0}}
</style>
</head>
<body><div class="layout"><nav aria-label="文档目录"><strong>和序 · 技术文档</strong>${toc.join('\n')}</nav><main>
${body}
<footer>本文件的图表与样式全部内嵌，无需 CDN。离线阅读正文与图表；访问源码链接需要网络与仓库权限。</footer>
</main></div></body></html>\n`;
if ((html.match(/<svg\b/g) || []).length !== 3 || /<img\b/.test(html) || /(?:href|src)="(?:\.\.\/|diagrams\/)/.test(html)) {
  throw new Error('Portable HTML must contain all three SVGs and no external local resources');
}
await fs.writeFile(path.join(output, 'TECHNICAL_GUIDE.html'), html);
await fs.writeFile(path.join(output, 'README.md'), `# 文档分享包\n\n- TECHNICAL_GUIDE.html：推荐。可以单独复制到任意目录或电脑，双击浏览器打开，三张 SVG 图与样式已内嵌，无需联网。\n- TECHNICAL_GUIDE.md：Markdown 版。正文用 PNG 配图，请与 diagrams/ 目录一起移动；目录中同时保留可编辑的 SVG 原图。\n- 源码链接指向 Gitee 私有仓库，访问需要联网并登录，不影响离线阅读正文和图表。\n- 浏览器打印可另存 PDF；分页由浏览器决定。\n\n不要只从压缩包预览窗口打开 Markdown：先完整解压，再用阅读器打开。\n`);

// Deterministic ZIP (UTF-8 names, DEFLATE, fixed timestamp), using Node built-ins.
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
const entries = ['README.md', 'TECHNICAL_GUIDE.md', 'TECHNICAL_GUIDE.html', ...names.flatMap(name => [`diagrams/${name}.svg`, `diagrams/${name}.png`])];
const localParts = [], centralParts = [];
let offset = 0;
for (const relative of entries) {
  const data = await fs.readFile(path.join(output, relative));
  const packed = deflateRawSync(data);
  const name = Buffer.from(relative), crc = crc32(data);
  const header = Buffer.alloc(30);
  header.writeUInt32LE(0x04034b50, 0); header.writeUInt16LE(20, 4); header.writeUInt16LE(0x800, 6);
  header.writeUInt16LE(8, 8); header.writeUInt16LE(33, 12); header.writeUInt32LE(crc, 14);
  header.writeUInt32LE(packed.length, 18); header.writeUInt32LE(data.length, 22); header.writeUInt16LE(name.length, 26);
  localParts.push(header, name, packed);
  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6);
  central.writeUInt16LE(0x800, 8); central.writeUInt16LE(8, 10); central.writeUInt16LE(33, 14);
  central.writeUInt32LE(crc, 16); central.writeUInt32LE(packed.length, 20); central.writeUInt32LE(data.length, 24);
  central.writeUInt16LE(name.length, 28); central.writeUInt32LE(offset, 42);
  centralParts.push(central, name); offset += header.length + name.length + packed.length;
}
const central = Buffer.concat(centralParts), end = Buffer.alloc(22);
end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
end.writeUInt32LE(central.length, 12); end.writeUInt32LE(offset, 16);
await fs.writeFile(path.join(docs, 'TECHNICAL_GUIDE_PORTABLE.zip'), Buffer.concat([...localParts, central, end]));
console.log(`Exported ${entries.length} files, self-contained HTML and portable ZIP to ${esc(output)}`);
