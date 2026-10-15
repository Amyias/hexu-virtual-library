import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "../public/vendor/three.module.js";
import { projectDialogueAnchor } from "../src/app/project-dialogue.js";

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
