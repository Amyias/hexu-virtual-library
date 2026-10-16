import * as THREE from "three";
import { IDLE, READING } from "./phases.js";

/* Pointer, wheel, keyboard and button wiring. In IDLE the pointer orbits the library and the
   wheel zooms; while reading it turns the cover. Everything else is ignored mid-walk. */
export function bindInput({
  $,
  canvas,
  machine,
  view,
  journey,
  assistant,
  feedback,
  library,
  novelReader,
  orbit,
  focus,
  updateCamera,
  camera,
  renderer,
  petRoot,
}) {
  let orbitDrag = null;
  let tap = null;
  const petRay = new THREE.Raycaster();
  const petPointer = new THREE.Vector2();

  canvas.addEventListener("pointerdown", (event) => {
    if (view.inspecting || event.button !== 0) return;
    tap = { x: event.clientX, y: event.clientY };
    if (machine.is(READING)) {
      if (view.grab(event)) canvas.setPointerCapture(event.pointerId);
    } else if (machine.is(IDLE)) {
      orbitDrag = { x: event.clientX, y: event.clientY };
      canvas.setPointerCapture(event.pointerId);
    }
  });
  canvas.addEventListener("pointermove", (event) => {
    if (tap && Math.hypot(event.clientX - tap.x, event.clientY - tap.y) > 5) tap = null;
    if (view.dragTo(event.clientX)) return;
    if (!orbitDrag || !machine.is(IDLE)) return;
    orbit.angle -= (event.clientX - orbitDrag.x) * 0.005;
    orbit.elevation = THREE.MathUtils.clamp(
      orbit.elevation + (event.clientY - orbitDrag.y) * 0.003,
      0.2,
      1.2,
    );
    orbitDrag = { x: event.clientX, y: event.clientY };
    updateCamera();
  });
  const release = () => {
    view.letGo();
    orbitDrag = null;
    tap = null;
  };
  canvas.addEventListener("pointerup", (event) => {
    if (tap && machine.is(IDLE)) {
      const rect = canvas.getBoundingClientRect();
      petPointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        (-(event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      petRay.setFromCamera(petPointer, camera);
      petRoot.updateMatrixWorld(true);
      if (
        petRay
          .intersectObject(petRoot, true)
          .some((hit) => /^Pet(?:Body|Eye|Arm|Leg)/.test(hit.object.name))
      )
        assistant.processText("小和", true);
    }
    tap = null;
    release();
  });
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("lostpointercapture", release);
  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      if (!machine.is(IDLE)) return;
      orbit.radius = THREE.MathUtils.clamp(orbit.radius + event.deltaY * 0.016, 12, 38);
      updateCamera();
    },
    { passive: false },
  );

  $("openBook").onclick = () => {
    if (machine.is(READING)) view.toggleCover();
  };
  $("returnBook").onclick = () => {
    assistant.cancelPending();
    journey.returnBook();
  };
  $("inspectChip").onclick = () => view.openChip(journey.selected);
  $("closeChip").onclick = () => view.closeChip();
  $("readText").onclick = () => assistant.openFullText();
  $("home").onclick = () => {
    if (!machine.is(IDLE)) return;
    const { angle, elevation, radius, focus: front } = journey.overview;
    Object.assign(orbit, { angle, elevation, radius });
    focus.copy(front);
    updateCamera();
  };
  $("sound").onclick = feedback.toggleSpeaking;
  $("dialogueSound").onclick = feedback.toggleSounds;
  document.addEventListener("keydown", (event) => {
    if (
      event.target.closest("#conversation") ||
      event.target.matches("textarea, input, [contenteditable]")
    )
      return;
    if (library.opened) {
      if (event.key === "Escape") library.close();
      return;
    }
    if (novelReader.handleKey(event)) return;
    if (event.target.matches("input")) return;
    if (view.inspecting) {
      if (event.key === "Escape") view.closeChip();
      return;
    }
    if (!machine.is(READING)) return;
    if (event.key === "Escape") journey.returnBook();
    if (event.key === "ArrowLeft") view.animateTurn(1);
    if (event.key === "ArrowRight") view.animateTurn(0);
  });

  window.addEventListener("resize", () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
    if (machine.is(READING)) view.position();
    view.positionChip();
  });
}
