import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createHash } from "node:crypto";

const read = (file) => fs.readFileSync(new URL("../" + file, import.meta.url));
test("Blender companion preserves the reference silhouette and an independently animated rig", () => {
  const buffer = read("public/models/xiaohe-pet.glb");
  assert.equal(buffer.readUInt32LE(0), 0x46546c67);
  assert.equal(buffer.readUInt32LE(8), buffer.length);
  const gltf = JSON.parse(buffer.subarray(20, 20 + buffer.readUInt32LE(12)).toString());
  const names = gltf.nodes.map((n) => n.name);
  for (const name of [
    "XiaoHePet",
    "PetBody",
    "PetEyeLeft",
    "PetEyeRight",
    "PetArmLeft",
    "PetArmRight",
    "PetLeg1",
    "PetLeg2",
    "PetLeg3",
    "PetLeg4",
  ])
    assert.ok(names.includes(name), name);
  assert.equal(gltf.meshes.length, 9);
  assert.equal(names.filter((n) => /^PetLeg[1-4]$/.test(n)).length, 4);
  assert.equal(gltf.images?.length ?? 0, 0, "geometry and PBR materials, no sprite replacement");
  const root = gltf.nodes.find((n) => n.name === "XiaoHePet");
  assert.equal(root.extras.reference_color, "#D87656");
  assert.ok(Math.abs(root.extras.width_m - 0.78) < 1e-5);
  assert.ok(Math.abs(root.extras.height_m - 0.5260465) < 1e-5);
  assert.ok(buffer.length < 100000);
  const manifest = JSON.parse(read("blender/xiaohe-pet-manifest.json"));
  assert.equal(manifest.triangles, 396);
  for (const [file, digest] of Object.entries(manifest.protected_assets))
    assert.equal(
      createHash("sha256").update(read(file)).digest("hex"),
      digest,
      file + " must be unchanged by pet replacement",
    );
});
