import * as THREE from "three";
import { READING } from "./phases.js";

/* The book in the reader's hands: its 3D model, how far the cover is turned, the drag that turns
   it, and the chip close-up that stands in for it while the chip is inspected.

   `turn` runs from 0 (closed) to 1 (cover laid flat); the hinge turns the cover about the spine by
   -π × turn, and the book slides right as it opens so the open spread stays centred. */
export function createReaderView({ gsap, $, scene, camera, factory, machine, readingMusic, novelReader }) {
  let book = null; // the volume's 3D root
  let hinge = null;
  let turn = 0;
  let drag = null;
  let turnTween = null;
  let chip = null;
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  // Book and chip sit this far in front of the camera.
  const ahead = (x = 0) => new THREE.Vector3(x, 0, -5.3).applyQuaternion(camera.quaternion);

  function scale() {
    return Math.min(1, (innerWidth / innerHeight) * 1.34);
  }

  function position() {
    if (!book) return;
    const s = scale();
    book.scale.setScalar(s);
    book.position.copy(camera.position).add(ahead(0.7 * turn * s));
  }

  /** Take the volume off its shelf: the model appears exactly where the shelved spine was. */
  function take(volume) {
    ({ root: book, hinge } = factory.create(volume));
    turn = 0;
    book.position.copy(volume.origin);
    book.scale.setScalar(0.15);
    book.rotation.y = volume.side === "A" ? Math.PI / 2 : -Math.PI / 2;
    scene.add(book);
    return book;
  }

  function release() {
    factory.dispose(book);
    book = null;
    hinge = null;
  }

  function setTurn(value) {
    turn = THREE.MathUtils.clamp(value, 0, 1);
    if (!hinge) return;
    hinge.rotation.y = -Math.PI * turn;
    if (machine.is(READING) && turn > 0.85) readingMusic.start();
    novelReader.cover(turn > 0.85);
    position();
    $("openBook").textContent = turn > 0.5 ? "合上封面" : "翻开书页";
    $("dragHint").textContent = turn > 0.85 ? "每一本书，都是通往另一个世界的入口。" : "按住封面向左拖动，让故事从这里展开";
  }

  function animateTurn(value) {
    turnTween?.kill();
    const state = { value: turn };
    turnTween = gsap.to(state, { value, duration: 0.65, ease: "power2.out", onUpdate: () => setTurn(state.value) });
  }

  /** Close the cover before the book goes back; resolves once it is shut. */
  function shut() {
    drag = null;
    turnTween?.kill();
    const state = { value: turn };
    return new Promise((resolve) =>
      gsap.to(state, { value: 0, duration: 0.55, onUpdate: () => setTurn(state.value), onComplete: resolve }),
    );
  }

  /** A press on the cover starts a drag; returns false when it missed the book. */
  function grab(event) {
    if (!machine.is(READING) || !book) return false;
    pointer.set((event.clientX / innerWidth) * 2 - 1, 1 - (event.clientY / innerHeight) * 2);
    raycaster.setFromCamera(pointer, camera);
    if (!raycaster.intersectObject(book, true).length) return false;
    turnTween?.kill();
    drag = { x: event.clientX, start: turn };
    return true;
  }

  /** Dragging left opens the cover; returns false when no drag is in progress. */
  function dragTo(clientX) {
    if (!drag || !machine.is(READING)) return false;
    setTurn(drag.start + (drag.x - clientX) / Math.min(330, innerWidth * 0.43));
    return true;
  }

  /** Let go: the cover settles open or shut, whichever it is nearer. */
  function letGo() {
    if (drag && machine.is(READING)) animateTurn(turn > 0.38 ? 1 : 0);
    drag = null;
  }

  function positionChip() {
    if (!chip) return;
    chip.position.copy(camera.position).add(ahead());
    chip.quaternion.copy(camera.quaternion);
    chip.scale.setScalar(scale());
  }

  function openChip(volume) {
    if (!machine.is(READING) || chip) return;
    novelReader.hide();
    drag = null;
    chip = factory.createChip(volume);
    scene.add(chip);
    positionChip();
    book.visible = false;
    $("chipId").textContent = volume.chipId;
    $("chipLocation").textContent = `${volume.locationCode} · ${volume.shelf} 号书架 / ${volume.side} 面 / 第 ${volume.layer} 层 / 第 ${volume.slot} 本`;
    document.body.classList.add("inspecting");
  }

  function closeChip() {
    if (!chip) return;
    factory.dispose(chip);
    chip = null;
    book.visible = true;
    document.body.classList.remove("inspecting");
  }

  return {
    get book() {
      return book;
    },
    get turn() {
      return turn;
    },
    get inspecting() {
      return Boolean(chip);
    },
    scale,
    position,
    take,
    release,
    animateTurn,
    toggleCover: () => animateTurn(turn > 0.5 ? 0 : 1),
    shut,
    grab,
    dragTo,
    letGo,
    openChip,
    closeChip,
    positionChip,
  };
}
