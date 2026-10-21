import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const read = (file) => fs.readFileSync(new URL("../" + file, import.meta.url));

test("Blender pixel sun and moon ship as light flat-colour geometry", () => {
  const buffer = read("public/models/celestial.glb");
  assert.equal(buffer.readUInt32LE(0), 0x46546c67);
  assert.equal(buffer.readUInt32LE(8), buffer.length);
  const gltf = JSON.parse(buffer.subarray(20, 20 + buffer.readUInt32LE(12)).toString());
  const names = gltf.nodes.map((n) => n.name);
  for (const name of [
    "PixelSun",
    "PixelSunDisc",
    "PixelSunRays",
    "PixelMoon",
    "PixelMoonFace",
    "PixelMoonStars",
  ])
    assert.ok(names.includes(name), name);
  assert.equal(gltf.meshes.length, 4);
  assert.equal(gltf.images?.length ?? 0, 0, "pixels are voxels, not a sprite texture");
  assert.ok(buffer.length < 100000);
  const manifest = JSON.parse(read("blender/celestial-manifest.json"));
  assert.equal(manifest.grid, 22);
  assert.equal(manifest.bodies.PixelSun.width_m, 1.76, "sun rays reach every edge of the grid");
  for (const body of Object.values(manifest.bodies)) assert.ok(body.triangles < 3000);
});

test("the sky body sits outside the window on the daylight's bearing and shows through glass", () => {
  const rig = JSON.parse(read("public/models/lighting-rig.json"));
  const [sx, , sz] = rig.sun.position,
    [tx, , tz] = rig.sun.target;
  const [x, y, z] = rig.sky.position;
  // Same compass bearing as the light: the floor shadows point straight away from the body.
  const light = [sx - tx, sz - tz],
    body = [x - tx, z - tz];
  const cross = light[0] * body[1] - light[1] * body[0];
  assert.ok(Math.abs(cross) / Math.hypot(...light) / Math.hypot(...body) < 0.01, "bearing");
  assert.ok(light[0] * body[0] + light[1] * body[1] > 0, "on the light's side, not opposite");
  assert.ok(z < -10.5, "outside the rear wall");
  // From the overview camera (journey.js) the line of sight crosses the rear wall inside the
  // second arched window opening rather than hitting the pier or the lintel.
  const angle = 0.44,
    elevation = 0.65,
    radius = 26;
  const eye = [
    Math.sin(angle) * Math.cos(elevation) * radius,
    Math.sin(elevation) * radius,
    -1.2 + Math.cos(angle) * Math.cos(elevation) * radius,
  ];
  const f = (eye[2] + 10.3) / (eye[2] - z);
  const wx = eye[0] + f * (x - eye[0]),
    wy = eye[1] + f * (y - eye[1]);
  const dx = Math.abs(wx + 5);
  assert.ok(dx < 1.35, `crosses window x=${wx}`);
  assert.ok(wy > 1.3 && wy < 3 + 1.25 * Math.sqrt(1 - (dx / 1.48) ** 2), `crosses window y=${wy}`);
});

test("the sky follows the local clock and a manual choice lapses at the next 08:00 or 17:00", async () => {
  const { isNightAt, nextBoundary, readOverride } = await import("../src/scene/sky-schedule.js");
  const at = (hour, minute = 0) => new Date(2026, 9, 21, hour, minute);
  for (const [hour, minute, night] of [
    [0, 0, true],
    [7, 59, true],
    [8, 0, false],
    [12, 30, false],
    [16, 59, false],
    [17, 0, true],
    [23, 59, true],
  ])
    assert.equal(isNightAt(at(hour, minute)), night, `${hour}:${minute}`);
  assert.deepEqual(nextBoundary(at(6, 15)), at(8));
  assert.deepEqual(nextBoundary(at(8, 0)), at(17));
  assert.deepEqual(nextBoundary(at(16, 59)), at(17));
  assert.deepEqual(nextBoundary(at(17, 0)), new Date(2026, 9, 22, 8));
  assert.deepEqual(nextBoundary(at(23, 30)), new Date(2026, 9, 22, 8));
  // Crossing a month end still lands on the next morning.
  assert.deepEqual(nextBoundary(new Date(2026, 9, 31, 20)), new Date(2026, 10, 1, 8));
  const saved = JSON.stringify({ night: true, until: +at(17) });
  assert.deepEqual(readOverride(saved, at(10)), { night: true, until: +at(17) });
  assert.equal(readOverride(saved, at(17)), null, "expired at the boundary");
  for (const broken of [null, "", "night", "{}", '{"night":"yes","until":1}'])
    assert.equal(readOverride(broken, at(10)), null);
});
