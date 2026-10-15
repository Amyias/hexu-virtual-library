import * as THREE from "three";
import { READING } from "./phases.js";

/* The two long choreographies — fetching a book to the reader and putting it back — and the phase
   transitions that bracket them. Each step waits for the previous animation, so the phase always
   says which part of the walk is under way. */
export function createJourney({
  $,
  machine,
  motion,
  view,
  environment,
  orb,
  camera,
  orbit,
  home,
  anchors,
  feedback,
  attention,
  novelReader,
  readingMusic,
}) {
  let selected = null;
  const { moveTo, cameraTo } = motion;
  // The front-desk view the scene starts in, and returns to after every book.
  const overview = {
    angle: 0.44,
    elevation: 0.65,
    radius: 26,
    focus: new THREE.Vector3(0, 0, -1.2),
  };

  async function fetchBook(volume, target) {
    if (!machine.send("navigate")) return;
    selected = volume;
    novelReader.attach(volume);
    $("locationText").textContent =
      `${target.shelf_id} · ${volume.side} 面 · 第 ${volume.layer} 层`;
    $("voiceTitle").textContent = "小和正在为你取书";
    const landing = new THREE.Vector3(...target.world_position);
    motion.showRoute(landing);
    await moveTo(orb.position, new THREE.Vector3(0, 1.9, 3.3), 0.65);
    await moveTo(orb.position, new THREE.Vector3(landing.x, landing.y + 0.55, 1.5), 1.15);
    await moveTo(orb.position, landing, 0.8);
    feedback.bubble(`找到《${volume.title}》 · ${volume.side} 面第 ${volume.layer} 层`);
    environment.shelfBooks.highlight(volume, true);
    await motion.pause(700);

    machine.send("arrive");
    const book = view.take(volume);
    environment.shelfBooks.setVisible(volume, false);
    environment.shelfBooks.highlight(volume, false);
    await cameraTo(new THREE.Vector3(0, 5.2, 16), new THREE.Vector3(0, 1.3, 2), 1.2);
    const destination = camera.position
      .clone()
      .add(new THREE.Vector3(0, 0, -5.3).applyQuaternion(camera.quaternion));
    const euler = new THREE.Euler().setFromQuaternion(camera.quaternion);
    const s = view.scale();
    await Promise.all([
      moveTo(book.position, destination, 1.4),
      moveTo(book.rotation, euler, 1.4),
      moveTo(book.scale, new THREE.Vector3(s, s, s), 1.4),
    ]);

    machine.send("present");
    document.body.classList.add("reading");
    $("reader").classList.add("show");
    /* 书名已印在封面上，浮层不再重复；位置信息保留，书名交给读屏软件读取。 */
    $("reader").setAttribute("aria-label", `${volume.title} · 书籍阅读特写`);
    $("bookLocation").textContent =
      `${volume.bookId} / ${volume.side} 面 / 第 ${volume.layer} 层 / 第 ${volume.slot} 本`;
    $("dragHint").textContent = "按住封面向左拖动，让故事从这里展开";
    $("openBook").textContent = "翻开书页";
    $("readText").textContent = volume.localBookId ? "阅读本地正文" : "查找正文";
    $("returnBook").disabled = false;
  }

  async function returnBook() {
    if (!machine.is(READING)) return;
    readingMusic.stop();
    novelReader.clear();
    view.closeChip();
    machine.send("return");
    $("returnBook").disabled = true;
    await view.shut();
    $("reader").classList.remove("show");
    document.body.classList.remove("reading");
    const volume = selected;
    const book = view.book;
    await Promise.all([
      moveTo(book.position, volume.origin, 1.45),
      moveTo(book.scale, new THREE.Vector3(0.15, 0.15, 0.15), 1.45),
      moveTo(
        book.rotation,
        new THREE.Vector3(0, volume.side === "A" ? Math.PI / 2 : -Math.PI / 2, 0),
        1.45,
      ),
    ]);
    view.release();
    environment.shelfBooks.setVisible(volume, true);
    motion.clearRoute();
    await moveTo(orb.position, new THREE.Vector3(anchors[volume.shelf - 1], 1.8, 2), 0.65);
    await moveTo(orb.position, home, 1.4);
    Object.assign(orbit, {
      angle: overview.angle,
      elevation: overview.elevation,
      radius: overview.radius,
    });
    const { angle, elevation, radius, focus } = overview;
    const eye = new THREE.Vector3(
      Math.sin(angle) * Math.cos(elevation) * radius,
      Math.sin(elevation) * radius,
      focus.z + Math.cos(angle) * Math.cos(elevation) * radius,
    );
    await cameraTo(eye, focus.clone(), 1);

    machine.send("shelve");
    selected = null;
    attention.clear();
    $("voiceTitle").textContent = "说一声「小和」，开启一段探索";
    $("locationText").textContent = "前台服务区 · 小和待命中";
    feedback.bubble("书已归位，小和在这里等你。");
  }

  return {
    get selected() {
      return selected;
    },
    overview,
    fetchBook,
    returnBook,
  };
}
