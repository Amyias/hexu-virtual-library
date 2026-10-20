import test from "node:test";
import assert from "node:assert/strict";
import { createLensMap } from "../src/reader/music-glass.js";

test("music lens leaves the centre clear and bends opposite rims symmetrically", () => {
  const map = createLensMap(320, 180);
  const at = (x, y) => [...map.pixels.slice((y * map.width + x) * 4, (y * map.width + x) * 4 + 4)];
  assert.deepEqual(at(160, 90), [128, 128, 128, 255]);
  const left = at(2, 90),
    right = at(317, 90);
  const top = at(160, 2),
    bottom = at(160, 177);
  assert.ok(left[0] > 200 && right[0] < 56);
  assert.equal(left[0] + right[0], 256);
  assert.equal(top[1] + bottom[1], 256);
  assert.equal(left[1], 128);
  assert.equal(top[0], 128);
  const corner = at(15, 5);
  assert.ok(corner[0] > 128 && corner[1] > 128, "corners bend along both axes");
});

test("responsive music lens has bounded work for wide, compact and hidden players", () => {
  for (const [w, h] of [
    [1800, 105],
    [320, 180],
    [280, 200],
    [1, 1],
    [10000, 2000],
  ]) {
    const map = createLensMap(w, h);
    assert.ok(map.width <= 1024 && map.height <= 256);
    assert.equal(map.pixels.length, map.width * map.height * 4);
    for (let i = 3; i < map.pixels.length; i += 4) assert.equal(map.pixels[i], 255);
  }
  assert.equal(createLensMap(0, 0), null);
});
