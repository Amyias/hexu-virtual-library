// Fetches the CC0 PBR texture sets the library materials are built from.
//
// Sources are Poly Haven (https://polyhaven.com), licensed CC0 — public domain, so the
// files are redistributable and are committed alongside the model like every other asset.
// Slugs and their roles are recorded here and in blender/MATERIAL_REFERENCES.md; re-running
// this script is how the textures are reproduced from scratch.
//
//   node tools/fetch-textures.mjs
//
// Idempotent: files already present at the expected size are left alone. Pass --force to
// refetch.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(ROOT, "public", "textures");
const RESOLUTION = "1k";
const force = process.argv.includes("--force");

/* Each entry is one material's albedo, normal and roughness map. The polyhaven slug is the
   upstream asset id; the output names describe the role in this scene, so swapping a source
   never renames a texture the model already references.

   Both sources are seamless single surfaces. That matters: the floor and shelving geometry
   already models its own boards, so a texture with its own plank seams would cut a second,
   conflicting set of seams across them. They also carry visible grain figure — the
   Wood/Veneer family is too uniform to read as timber at any distance. */
const SETS = [
  {
    material: "地板 · 橡木",
    slug: "wood_table_worn",
    outputs: { Diffuse: "floor-oak-albedo.jpg", nor_gl: "floor-oak-normal.jpg", Rough: "floor-oak-roughness.jpg" },
  },
  {
    material: "书柜 · 橡木",
    slug: "red_oak_veneer",
    outputs: { Diffuse: "joinery-oak-albedo.jpg", nor_gl: "joinery-oak-normal.jpg", Rough: "joinery-oak-roughness.jpg" },
  },
];

async function fetchMap(slug, map, filename) {
  const target = path.join(OUT, filename);
  const meta = await fetch(`https://api.polyhaven.com/files/${slug}`).then((r) => r.json());
  const info = meta[map]?.[RESOLUTION]?.jpg;
  if (!info) throw new Error(`${slug}: no ${map} at ${RESOLUTION}`);
  if (!force && fs.existsSync(target) && fs.statSync(target).size === info.size) {
    return { filename, bytes: info.size, skipped: true, url: info.url };
  }
  const res = await fetch(info.url);
  if (!res.ok) throw new Error(`${slug}: ${map} download failed HTTP ${res.status}`);
  const bytes = Buffer.from(await res.arrayBuffer());
  if (bytes.length !== info.size) {
    throw new Error(`${filename}: got ${bytes.length} bytes, API reported ${info.size}`);
  }
  fs.writeFileSync(target, bytes);
  return { filename, bytes: bytes.length, skipped: false, url: info.url };
}

fs.mkdirSync(OUT, { recursive: true });
let total = 0;
for (const set of SETS) {
  console.log(`${set.material}  (polyhaven:${set.slug}, CC0)`);
  for (const [map, filename] of Object.entries(set.outputs)) {
    const r = await fetchMap(set.slug, map, filename);
    total += r.bytes;
    console.log(`  ${r.skipped ? "已有" : "下载"}  ${filename.padEnd(28)} ${(r.bytes / 1024).toFixed(0)} KB`);
  }
}
console.log(`\n${SETS.length} 套材质，合计 ${(total / 1048576).toFixed(2)} MB，写入 public/textures/`);
