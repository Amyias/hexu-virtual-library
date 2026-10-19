import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "../public/vendor/three.module.js";
import { projectDialogueAnchor, placeDialogue } from "../src/app/project-dialogue.js";

const anchor = new THREE.Vector3(0, 1.2, 5);
const offset = new THREE.Vector3(0, 0.63, 0);
const pixelError = (a, b) => Math.hypot((a.x - b.x) * 720, (a.y - b.y) * 480);
function rendererProjection(camera) {
  camera.updateWorldMatrix(true, false);
  return anchor.clone().add(offset).project(camera);
}

test("dragging the camera cannot make the bubble jump when the renderer updates its matrices", () => {
  const camera = new THREE.PerspectiveCamera(39, 1.5, 0.1, 100);
  const focus = new THREE.Vector3(0, 0, -1.2);
  camera.position.set(10, 14, 20);
  camera.lookAt(focus);
  camera.updateMatrixWorld(true);
  const target = new THREE.Vector3();
  let worst = 0;
  for (let i = 0; i < 160; i++) {
    const angle = 0.44 + i * 0.018,
      elevation = 0.65 + Math.sin(i * 0.05) * 0.1,
      radius = 26;
    camera.position.set(
      Math.sin(angle) * Math.cos(elevation) * radius,
      Math.sin(elevation) * radius,
      focus.z + Math.cos(angle) * Math.cos(elevation) * radius,
    );
    camera.lookAt(focus); // This is exactly the drag call site: no render has happened yet.
    const before = projectDialogueAnchor(camera, anchor, offset, target).clone();
    const after = rendererProjection(camera);
    worst = Math.max(worst, pixelError(before, after));
    assert.equal(projectDialogueAnchor(camera, anchor, offset, target), target);
  }
  assert.ok(worst < 0.01, `Uncommanded bubble jump of ${worst.toFixed(3)} pixels`);
  assert.deepEqual(anchor.toArray(), [0, 1.2, 5]);
  assert.deepEqual(offset.toArray(), [0, 0.63, 0]);
});

test("camera flights and parent transforms also project the current frame", () => {
  const parent = new THREE.Group();
  const camera = new THREE.PerspectiveCamera(39, 1.5, 0.1, 100);
  parent.add(camera);
  camera.position.set(0, 8, 20);
  camera.lookAt(0, 1, 2);
  parent.updateMatrixWorld(true);
  const target = new THREE.Vector3();
  for (let i = 0; i < 64; i++) {
    parent.rotation.y = i * 0.004;
    parent.position.x = i * 0.01;
    camera.position.y = 8 - i * 0.04;
    camera.lookAt(0, 1, 2);
    const before = projectDialogueAnchor(camera, anchor, offset, target).clone();
    assert.ok(pixelError(before, rendererProjection(camera)) < 0.01);
  }
});

test("auto-sized replies move beside the pet when clamping them above would hide it", () => {
  const ctx = {
    viewWidth: 1280,
    viewHeight: 820,
    bubbleWidth: 360,
    bubbleHeight: 570,
    anchorX: 640,
    anchorY: 380,
    pet: { left: 610, right: 670, top: 410, bottom: 470 },
  };
  const short = placeDialogue({ ...ctx, bubbleWidth: 240, bubbleHeight: 110 });
  assert.equal(short.placement, "above");
  assert.equal(short.maxHeight, 110);
  const long = placeDialogue(ctx);
  assert.equal(long.placement, "right");
  assert.equal(long.maxHeight, 570);
  assert.ok(long.left - ctx.bubbleWidth / 2 >= ctx.pet.right + 24);
  const left = placeDialogue({
    ...ctx,
    anchorX: 1100,
    pet: { left: 1070, right: 1130, top: 410, bottom: 470 },
  });
  assert.equal(left.placement, "left");
  assert.equal(placeDialogue({ ...ctx, bubbleHeight: 350 }).placement, "above");
  const held = placeDialogue({ ...ctx, bubbleHeight: 350, previous: "right" });
  assert.equal(held.placement, "right");
});

test("narrow-screen replies keep the pet visible and remain inside the viewport", () => {
  for (const [viewWidth, viewHeight] of [
    [390, 740],
    [667, 375],
    [1280, 820],
  ]) {
    for (const cy of [80, viewHeight / 2, viewHeight - 80]) {
      const pet = {
        left: viewWidth / 2 - 28,
        right: viewWidth / 2 + 28,
        top: cy - 25,
        bottom: cy + 25,
      };
      const bubbleWidth = Math.min(360, viewWidth - 32);
      const placed = placeDialogue({
        viewWidth,
        viewHeight,
        bubbleWidth,
        bubbleHeight: 600,
        anchorX: viewWidth / 2,
        anchorY: pet.top - 20,
        pet,
      });
      const left = placed.left - bubbleWidth / 2,
        right = placed.left + bubbleWidth / 2;
      const top = placed.top - placed.maxHeight,
        bottom = placed.top;
      assert.ok(
        left >= 15 && right <= viewWidth - 15 && top >= 15 && bottom <= viewHeight - 15,
        JSON.stringify(placed),
      );
      assert.ok(
        right <= pet.left - 23 ||
          left >= pet.right + 23 ||
          bottom <= pet.top - 23 ||
          top >= pet.bottom + 23,
        JSON.stringify(placed),
      );
    }
  }
  const pinned = placeDialogue({
    viewWidth: 1280,
    viewHeight: 820,
    bubbleWidth: 360,
    bubbleHeight: 550,
    anchorX: 640,
    anchorY: 400,
    pet: { left: 610, right: 670, top: 410, bottom: 470 },
    pinned: true,
  });
  assert.equal(pinned.placement, "pinned");
});
