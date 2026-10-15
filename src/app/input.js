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
}) {
  let orbitDrag = null;

  canvas.addEventListener("pointerdown", (event) => {
    if (view.inspecting || event.button !== 0) return;
    if (machine.is(READING)) {
      if (view.grab(event)) canvas.setPointerCapture(event.pointerId);
    } else if (machine.is(IDLE)) {
      orbitDrag = { x: event.clientX, y: event.clientY };
      canvas.setPointerCapture(event.pointerId);
    }
  });
  canvas.addEventListener("pointermove", (event) => {
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
  };
  canvas.addEventListener("pointerup", release);
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
  $("returnBook").onclick = () => journey.returnBook();
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
  $("searchForm").onsubmit = (event) => {
    event.preventDefault();
    const text = $("query").value.trim();
    if (!text) return;
    $("transcript").textContent = "输入：" + text;
    assistant.processText(text, true);
    $("query").value = "";
  };
  document.addEventListener("keydown", (event) => {
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
