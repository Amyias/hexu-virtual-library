import fs from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { expandInventory } from "../src/data/inventory.js";
const names = [
  "计算机与AI技术",
  "文学与历史哲学",
  "商业经济与管理",
  "艺术设计与建筑",
  "科幻与未来馆藏",
];
const colors = ["#466b60", "#7f6650", "#536c7d", "#886554", "#596879"];
// Each face is a bookcase with a 300 mm deep cavity and a solid back panel whose inner face
// stands 200 mm from the shelf centre plane. A volume is shelved spine to the aisle, so it is
// its fore-edge that rests on that panel; the spine ends up at 200 mm + the volume's own depth.
// See blender/SHELVING_REFERENCES.md.
const BACK_PANEL_FACE = 0.2;
// The frame posts divide each face into four bays, and a row is packed along the spine — the
// thickness axis now, not the cover. That is what makes a real shelf: 1.85 m of bay holds
// roughly seventy 25 mm spines, not eight 216 mm covers.
const POSTS = [-8.75, -6.8, -4.8, -2.8, -0.85];
const POST = 0.1;
const CLEAR = 0.003; // air at each end of a bay, so no volume touches a post
const BAYS = POSTS.length - 1;
const BOARD_TOPS = [0.09, 0.535, 1.035, 1.535];
const HEIGHT = 0.306;
const WIDTH = 0.216;
const DEPTH = 0.026;
// Every volume is the same size: 216 x 306 x 26 mm, the dimensions the template is authored
// at. An earlier pass varied width, height and thickness the way a stocked shelf does, but a
// library reads as a library precisely when its volumes are uniform — and a varied size also
// pushed the interactive book out of the reader's frame, hiding the cover.
const SIZE = 1;
// Ten cloth shades per category. A real library orders its buckram from a finite range, and a
// continuous spread would make the .blend carry one material per volume.
const CLOTHS = 10;
/** Deterministic 0..1 from a string: FNV-1a mixed so the low bits do not track the last
 *  character of a sequential id (unmixed, that turns a row into a regular staircase). */
function rand(seed) {
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i++) hash = Math.imul(hash ^ seed.charCodeAt(i), 16777619);
  hash ^= hash >>> 15;
  hash = Math.imul(hash, 2246822507);
  hash ^= hash >>> 13;
  hash = Math.imul(hash, 3266489909);
  hash ^= hash >>> 16;
  return (hash >>> 0) / 4294967296;
}
const pick = (list, seed) => list[Math.floor(rand(seed) * list.length)];
/** A run of 1-3 volumes that came as a set: one cloth, so identical volumes stand together. */
function runs(seed) {
  const out = [];
  let index = 0;
  while (true) {
    const size = 1 + Math.floor(rand(`${seed}:set${index}`) * 3);
    out.push({ size, shade: Math.floor(rand(`${seed}:t${index}`) * CLOTHS) });
    index += size;
    if (index > 200) break;
  }
  return out;
}
/** One bay's row: identical spines shoulder to shoulder from the left frame post, with whatever
 *  is left over standing open at the end. Uniform volumes are what makes a library read as a
 *  library; only the cloth varies. */
function bayRow(seed, span) {
  const thickness = DEPTH * SIZE;
  const count = Math.floor((span - CLEAR) / thickness);
  const shades = [];
  for (const run of runs(seed)) for (let i = 0; i < run.size; i++) shades.push(run.shade);
  return Array.from({ length: count }, (_, i) => ({
    thickness,
    centre: i * thickness + thickness / 2,
    shade: shades[i % shades.length],
  }));
}
/** A book's cloth sits on its shelf's colour, one of ten shades, so a category reads as a
 *  family of related volumes rather than one dyed batch. */
function cloth(hex, shade) {
  const step = shade / (CLOTHS - 1);
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b),
    min = Math.min(r, g, b),
    l = (max + min) / 2;
  const s = max === min ? 0 : l > 0.5 ? (max - min) / (2 - max - min) : (max - min) / (max + min);
  let h = 0;
  if (max !== min) {
    if (max === r) h = ((g - b) / (max - min) + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / (max - min) + 2) / 6;
    else h = ((r - g) / (max - min) + 4) / 6;
  }
  const light = Math.min(0.86, Math.max(0.14, l * (0.82 + step * 0.36)));
  const sat = Math.min(1, s * (0.94 + step * 0.12));
  const q = light < 0.5 ? light * (1 + sat) : light + sat - light * sat;
  const p = 2 * light - q;
  const channel = (t) => (t < 0 ? t + 1 : t > 1 ? t - 1 : t);
  const to = (t) =>
    Math.round(
      255 *
        (t < 1 / 6
          ? p + (q - p) * 6 * t
          : t < 1 / 2
            ? q
            : t < 2 / 3
              ? p + (q - p) * (2 / 3 - t) * 6
              : p),
    );
  return (
    "#" +
    [h + 1 / 3, h, h - 1 / 3].map((t) => to(channel(t)).toString(16).padStart(2, "0")).join("")
  );
}
// Compatibility only: these physical IDs were previously skipped by local slot allocation.
// Keep their numeric order so existing imported books retain their chips and positions.
const DEFERRED_IDS = [215, 793, 2203, 2781, 4191, 5053, 6463, 7325, 8167, 9881, 10165, 10439];
const rows = [];
for (let shelf = 1; shelf <= 5; shelf++)
  for (const side of ["A", "B"])
    for (let layer = 1; layer <= 4; layer++)
      for (let bay = 0; bay < BAYS; bay++) {
        const row = bayRow(
          `S${shelf}${side}L${layer}B${bay}`,
          POSTS[bay + 1] - POSTS[bay] - POST - CLEAR * 2,
        );
        for (let place = 0; place < row.length; place++) {
          const slot =
            rows.filter((b) => b.shelf === shelf && b.side === side && b.layer === layer).length +
            1;
          const bookId = `HX-${String(rows.length + 1).padStart(5, "0")}`;
          const locationCode = `S${shelf}-${side}-L${layer}-P${String(slot).padStart(3, "0")}`;
          const size = row[place];
          rows.push({
            title: "",
            author: "",
            category: names[shelf - 1],
            shelf,
            side,
            layer,
            slot,
            color: cloth(colors[shelf - 1], size.shade),
            keys: [bookId, bookId.replace("-", ""), locationCode],
            synopsis: "",
            bookId,
            chipId: bookId,
            locationCode,
            widthScale: SIZE,
            heightScale: SIZE,
            depthScale: SIZE,
            worldPosition: [
              (shelf - 3) * 3 + (side === "A" ? 1 : -1) * (BACK_PANEL_FACE + (WIDTH * SIZE) / 2),
              +(BOARD_TOPS[layer - 1] + (HEIGHT * SIZE) / 2).toFixed(6),
              +(POSTS[bay] + POST / 2 + CLEAR + size.centre).toFixed(6),
            ],
            chipPayload: {
              book_id: bookId,
              shelf_id: `Shelf_${shelf}`,
              shelf_side: side,
              layer,
              slot,
              location_code: locationCode,
            },
          });
        }
      }
/** A row is packed, so the checks below are about touching and about the shelf's own limits,
 *  not about even spacing. The count per bay is whatever the drawn spine widths come to. */
const faceHalfThickness = (b) => (b.depthScale * DEPTH) / 2;
for (let shelf = 1; shelf <= 5; shelf++)
  for (const side of ["A", "B"])
    for (let layer = 1; layer <= 4; layer++)
      for (let bay = 0; bay < BAYS; bay++) {
        const row = rows
          .filter(
            (b) =>
              b.shelf === shelf &&
              b.side === side &&
              b.layer === layer &&
              Math.abs(b.worldPosition[2] - (POSTS[bay] + POSTS[bay + 1]) / 2) <
                (POSTS[bay + 1] - POSTS[bay]) / 2,
          )
          .sort((a, b) => a.slot - b.slot);
        const span = POSTS[bay + 1] - POSTS[bay] - POST - CLEAR * 2;
        if (row.length < 40)
          throw new Error(`Bay S${shelf}${side}L${layer}B${bay} holds only ${row.length} volumes`);
        const used = row.reduce((sum, b) => sum + faceHalfThickness(b) * 2, 0);
        if (used > span + 1e-6)
          throw new Error(
            `Bay S${shelf}${side}L${layer}B${bay} overflows by ${(used - span).toFixed(4)} m`,
          );
        if (used < span * 0.9)
          throw new Error(
            `Bay S${shelf}${side}L${layer}B${bay} only ${((used / span) * 100).toFixed(1)}% full`,
          );
        let edge = POSTS[bay] + POST / 2 + CLEAR;
        for (const b of row) {
          if (Math.abs(b.worldPosition[2] - (edge + faceHalfThickness(b))) > 5e-4)
            throw new Error(`${b.bookId} is not packed against its neighbour`);
          edge += faceHalfThickness(b) * 2;
        }
      }
for (const b of rows) {
  // Every volume is the template's own size. A varied shelf was tried and rejected: a library
  // reads as a library when its volumes match, and a wider volume also pushed the interactive
  // book out of the reader's frame, hiding its cover.
  if (b.widthScale !== SIZE || b.heightScale !== SIZE || b.depthScale !== SIZE)
    throw new Error(`${b.bookId} is not the standard size`);
  if (BACK_PANEL_FACE + WIDTH * SIZE > 0.4955 - 0.002)
    throw new Error(`${b.bookId} reaches past the brass lip`);
}
// Store physical slots only. Bibliographic data comes exclusively from the local book library.
// Expansion must reproduce every slot ID, chip and coordinate before anything is written.
const inventory = {
  _comment:
    "Generated by tools/prepare-smart-books.mjs; do not edit. Row i is empty slot HX-(i+1); real books come from the local reading library. Expanded by src/data/inventory.js.",
  format: 3,
  categories: names,
  library_deferred_ids: DEFERRED_IDS,
  columns: ["shelf", "side", "layer", "slot", "color", "x", "y", "z"],
  books: rows.map((b) => [b.shelf, b.side, b.layer, b.slot, b.color, ...b.worldPosition]),
};
if (!isDeepStrictEqual(expandInventory(inventory), rows))
  throw new Error("The compact inventory does not expand back to the laid-out books");
// A row to a line, so a regenerated inventory diffs as the volumes that actually moved.
const { books: packed, ...head } = inventory;
const text = JSON.stringify(head, null, 2).replace(
  /\n}$/,
  ',\n  "books": [\n' + packed.map((r) => "    " + JSON.stringify(r)).join(",\n") + "\n  ]\n}\n",
);
fs.writeFileSync("public/models/book-inventory.json", text);
console.log(`Prepared ${rows.length} empty shelf slots; no preset books.`);
