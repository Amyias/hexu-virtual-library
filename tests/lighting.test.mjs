import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { inflateSync } from "node:zlib";

test("empty shelf slots do not execute lighting shaders and revealing books preserves physical instance indices", async () => {
  const threeUrl = new URL("../public/vendor/three.module.js", import.meta.url).href;
  const THREE = await import(threeUrl);
  const source = fs
    .readFileSync(new URL("../src/scene/smart-books.js", import.meta.url), "utf8")
    .replace('from "three"', `from ${JSON.stringify(threeUrl)}`);
  const { createShelfBooks } = await import(
    `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
  );
  const scene = new THREE.Scene(),
    template = new THREE.Group();
  const part = new THREE.Mesh(
    new THREE.BoxGeometry(0.1, 0.3, 0.02),
    new THREE.MeshStandardMaterial(),
  );
  part.name = "Spine";
  template.add(part);
  const books = Array.from({ length: 5 }, (_, i) => ({
    bookId: `slot-${i}`,
    worldPosition: [i, 0, 0],
    side: "B",
    color: "#567854",
  }));
  const shelf = createShelfBooks(scene, template, books);
  assert.equal(shelf.drawCount, 0);
  books[3].localBookId = "downloaded";
  shelf.setVisible(books[3], true);
  assert.equal(shelf.drawCount, 4);
  assert.equal(books[3].instanceIndex, 3);
  const matrix = new THREE.Matrix4();
  scene.children[0].getMatrixAt(3, matrix);
  assert.equal(matrix.elements[12], 3, "the book keeps its original physical slot");
  books[0].localBookId = "imported";
  shelf.setVisible(books[0], true);
  shelf.setVisible(books[3], false);
  assert.equal(shelf.drawCount, 1);
  assert.equal(shelf.visibleCount, 1);
  shelf.setVisible(books[0], false);
  assert.equal(shelf.drawCount, 0);
  shelf.setVisible(books[3], true);
  assert.equal(shelf.drawCount, 4);
  assert.equal(books[3].instanceIndex, 3);
});

test("ground occlusion stays mostly open, with actual furniture contacts instead of a buried receiver", () => {
  const png = fs.readFileSync(
    new URL("../public/textures/library-contact-ao.png", import.meta.url),
  );
  assert.equal(png.subarray(1, 4).toString(), "PNG");
  const width = png.readUInt32BE(16),
    height = png.readUInt32BE(20);
  assert.deepEqual([width, height, png[24], png[25]], [2048, 2048, 8, 2]);
  const chunks = [];
  for (let offset = 8; offset < png.length;) {
    const size = png.readUInt32BE(offset);
    if (png.toString("ascii", offset + 4, offset + 8) === "IDAT")
      chunks.push(png.subarray(offset + 8, offset + 8 + size));
    offset += size + 12;
  }
  const raw = inflateSync(Buffer.concat(chunks)),
    stride = width * 3;
  const rows = Buffer.alloc(height * stride);
  function paeth(a, b, c) {
    const p = a + b - c,
      da = Math.abs(p - a),
      db = Math.abs(p - b),
      dc = Math.abs(p - c);
    return da <= db && da <= dc ? a : db <= dc ? b : c;
  }
  let sum = 0,
    dark = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    assert.ok(filter <= 4);
    for (let x = 0; x < stride; x++) {
      const index = y * stride + x;
      const a = x >= 3 ? rows[index - 3] : 0,
        b = y ? rows[index - stride] : 0;
      const c = y && x >= 3 ? rows[index - stride - 3] : 0;
      const prediction = [0, a, b, Math.floor((a + b) / 2), paeth(a, b, c)][filter];
      rows[index] = (raw[y * (stride + 1) + 1 + x] + prediction) & 255;
      if (x % 3 === 0) {
        sum += rows[index];
        if (rows[index] < 80) dark++;
      }
    }
  }
  const mean = sum / (width * height * 255),
    darkRatio = dark / (width * height);
  assert.ok(mean > 0.65 && mean < 0.98, `implausible floor AO mean ${mean}`);
  assert.ok(darkRatio > 0.03 && darkRatio < 0.4, `implausible contact coverage ${darkRatio}`);
  const at = (x, z) =>
    rows[
      (Math.floor(((z + 10.5) / 19) * height) * width + Math.floor(((x + 10) / 20) * width)) * 3
    ];
  assert.ok(at(0, -4) < 80, "centre shelf must contact the floor");
  assert.ok(at(2.4, 7.8) > 230, "unobstructed foreground must not be blackened");
});

test("lighting emitters occupy real aisle fixtures and use the same ground mapping as the Blender bake", () => {
  const rig = JSON.parse(
    fs.readFileSync(new URL("../public/models/lighting-rig.json", import.meta.url)),
  );
  assert.ok(rig.sun.position[2] < -10.5 && rig.sun.position[1] > 4.5);
  assert.equal(new Set(rig.pendants.map((p) => p.join(","))).size, 8);
  for (const [x, y, z] of rig.pendants) {
    assert.ok([-4.5, -1.5, 1.5, 4.5].includes(x) && [-6.8, -2.5].includes(z));
    assert.ok(y > 3.5 && y < 3.625, "light must sit under the housing, not inside its opaque top");
  }
  assert.deepEqual(rig.ground, { minX: -10, maxX: 10, minZ: -10.5, maxZ: 8.5 });
});
