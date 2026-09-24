import * as THREE from "three";
import { books, anchors, heights } from "./data/catalog.js";
import { wakeRE, findBook } from "./voice/intent.js";
import { createSpeech } from "./voice/speech.js";
import { createRuntime } from "./scene/runtime.js";
import { loadEnvironment } from "./scene/environment.js";
import { createOrb } from "./scene/orb.js";
import { createBookFactory } from "./reader/book.js";
const gsap = window.gsap;
export async function startLibrary() {
  if (!gsap) throw new Error("GSAP 动画依赖未能加载");
  const $ = (id) => document.getElementById(id);
  const home = new THREE.Vector3(0, 1.2, 5);
  let phase = "IDLE",
    awakeUntil = 0,
    selected = null,
    bookView = null,
    hinge = null,
    turn = 0,
    drag = null,
    speakEnabled = false;
  let noticeTimer, bubbleTimer, wakeTween;
  const navigation = { pulse: 0 };
  function notice(text) {
    $("notice").textContent = text;
    $("notice").style.display = "block";
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => ($("notice").style.display = "none"), 6500);
  }
  function bubble(text, hold = 6500) {
    $("bubble").textContent = text;
    $("bubble").classList.add("show");
    clearTimeout(bubbleTimer);
    if (hold)
      bubbleTimer = setTimeout(
        () => $("bubble").classList.remove("show"),
        hold,
      );
  }
  function say(text) {
    bubble(text);
    if (speakEnabled && window.speechSynthesis) {
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "zh-CN";
      u.rate = 1;
      const voice = speechSynthesis
        .getVoices()
        .find((v) => v.lang.startsWith("zh"));
      if (voice) u.voice = voice;
      speechSynthesis.speak(u);
    }
  }
  function response(text, book = null, wakeOnly = false) {
    const r = {
      speech: text,
      is_wake_only: wakeOnly,
      action: book ? "NAVIGATE_TO_BOOK" : "IDLE",
      target: book
        ? {
            shelf_id: "Shelf_" + book.shelf,
            shelf_side: book.side,
            layer: book.layer,
            world_position: [
              anchors[book.shelf - 1],
              heights[book.layer - 1],
              0,
            ],
          }
        : {
            shelf_id: "Shelf_1",
            shelf_side: "A",
            layer: 1,
            world_position: home.toArray(),
          },
      book_data: book
        ? {
            title: book.title,
            author: book.author,
            category: book.category,
            synopsis: book.synopsis,
          }
        : { title: "", author: "", category: "", synopsis: "" },
    };
    /* IDLE 中 target 是无动作占位；消费者必须先检查 action。 */ $(
      "protocol",
    ).textContent = JSON.stringify(r, null, 2);
    window.dispatchEvent(new CustomEvent("xiaohe-response", { detail: r }));
    return r;
  }
  function wake() {
    awakeUntil = Date.now() + 25000;
    wakeTween?.kill();
    navigation.pulse = 1;
    wakeTween = gsap.to(navigation, {
      pulse: 0,
      duration: 2.8,
      ease: "power2.out",
    });
    bubble("有什么需求吗？", 25000);
    $("voiceTitle").textContent = "我在，请告诉我书名或感兴趣的主题";
  }
  function processText(text, direct = false, wasInterimWake = false) {
    const match = text.match(wakeRE);
    const active = Date.now() < awakeUntil;
    if (!direct && !match && !active) return null;
    if (phase !== "IDLE") {
      if (/放回|归还|合上/.test(text) && phase === "READING") returnBook();
      else if (match || direct)
        notice("正在陪你阅读，请先将当前书籍放回书架。");
      return null;
    }
    const request = text
      .replace(wakeRE, "")
      .replace(/你好|您好|在吗|你在吗|嗨|嘿|哈喽|hello/gi, "")
      .replace(/[\s，。！？、,.!?]/g, "");
    if (!request) {
      if (!wasInterimWake) wake();
      const r = response("有什么需求吗？", null, true);
      /* 气泡回应不产生扬声器回声，持续倾听下一句话。 */ return r;
    }
    if (match && !wasInterimWake) wake();
    const b = findBook(request);
    if (!b) {
      awakeUntil = Date.now() + 25000;
      const msg = "暂未匹配到馆藏。试试“三体”“计算机基础”或“人工智能”。";
      response(msg);
      say(msg);
      return null;
    }
    awakeUntil = 0;
    const speech = match
      ? "好的，为您找到相关书籍，请随我来。"
      : "好的，正在为您定位…";
    const r = response(speech, b);
    say(speech);
    navigate(b, r.target);
    return r;
  }

  const canvas = $("scene");
  const { renderer, scene, camera, focus, orbit, updateCamera } =
    createRuntime(canvas);
  $("loading").querySelector("p").textContent = "正在加载 Blender 精细模型";
  const environment = await loadEnvironment(
    scene,
    books,
    (percent) =>
      ($("loading").querySelector("p").textContent =
        "正在加载 Blender 模型 " + percent + "%"),
  );
  const speech = createSpeech({
    $,
    notice,
    wake,
    processText,
    getPhase: () => phase,
  });
  const factory = createBookFactory(renderer, environment.bookTemplate);
  let chipView = null;
  function closeChip() {
    if (!chipView) return;
    factory.dispose(chipView);
    chipView = null;
    bookView.visible = true;
    document.body.classList.remove('inspecting');
  }
  function positionChip() {
    if (!chipView) return;
    chipView.position.copy(camera.position).add(new THREE.Vector3(0,0,-5.3).applyQuaternion(camera.quaternion));
    chipView.quaternion.copy(camera.quaternion);
    chipView.scale.setScalar(readerScale());
  }
  $('inspectChip').onclick = () => {
    if (phase !== 'READING' || chipView) return;
    drag = null;
    chipView = factory.createChip(selected);
    scene.add(chipView);
    positionChip();
    bookView.visible = false;
    $('chipId').textContent = selected.chipId;
    $('chipLocation').textContent = `${selected.locationCode} · ${selected.shelf} 号书架 / ${selected.side} 面 / 第 ${selected.layer} 层 / 第 ${selected.slot} 本`;
    document.body.classList.add('inspecting');
  };
  $('closeChip').onclick = closeChip;
  const { orb, coreMaterial, core, glow, rings } = createOrb(scene, home);
  const routeMat = new THREE.LineDashedMaterial({
    color: "#86a58c",
    dashSize: 0.13,
    gapSize: 0.12,
    transparent: true,
    opacity: 0.7,
  });
  let route = null;
  function moveTo(object, position, duration = 1.5, extra = {}) {
    return new Promise((resolve) =>
      gsap.to(object, {
        x: position.x,
        y: position.y,
        z: position.z,
        duration,
        ease: "power2.inOut",
        ...extra,
        onComplete: resolve,
      }),
    );
  }
  function cameraTo(position, target, duration = 1.7) {
    return Promise.all([
      moveTo(camera.position, position, duration),
      moveTo(focus, target, duration, { onUpdate: () => camera.lookAt(focus) }),
    ]).then(() => camera.lookAt(focus));
  }
  function makeRoute(target) {
    if (route) {
      scene.remove(route);
      route.geometry.dispose();
    }
    const curve = new THREE.CatmullRomCurve3([
      home.clone(),
      new THREE.Vector3(home.x, 1.7, 3.3),
      new THREE.Vector3(target.x, target.y + 1, 1.9),
      target,
    ]);
    route = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(curve.getPoints(80)),
      routeMat,
    );
    route.computeLineDistances();
    scene.add(route);
  }
  async function navigate(b, target) {
    if (phase !== "IDLE") return;
    phase = "NAVIGATING";
    selected = b;
    $("locationText").textContent =
      `${target.shelf_id} · ${b.side} 面 · 第 ${b.layer} 层`;
    $("voiceTitle").textContent = "小和正在为你取书";
    const landing = new THREE.Vector3(...target.world_position);
    makeRoute(landing);
    await moveTo(orb.position, new THREE.Vector3(0, 1.9, 3.3), 0.65);
    await moveTo(
      orb.position,
      new THREE.Vector3(landing.x, landing.y + 0.55, 1.5),
      1.15,
    );
    await moveTo(orb.position, landing, 0.8);
    bubble(`找到《${b.title}》 · ${b.side} 面第 ${b.layer} 层`);
    environment.shelfBooks.highlight(b, true);
    await new Promise((r) => setTimeout(r, 700));
    phase = "PRESENTING";
    ({ root: bookView, hinge } = factory.create(b));
    turn = 0;
    bookView.position.copy(b.origin);
    bookView.scale.setScalar(0.15);
    bookView.rotation.y = b.side === "A" ? Math.PI / 2 : -Math.PI / 2;
    scene.add(bookView);
    environment.shelfBooks.setVisible(b, false);
    environment.shelfBooks.highlight(b, false);
    const targetFocus = new THREE.Vector3(0, 1.3, 2);
    await cameraTo(new THREE.Vector3(0, 5.2, 16), targetFocus, 1.2);
    const destination = camera.position
      .clone()
      .add(new THREE.Vector3(0, 0, -5.3).applyQuaternion(camera.quaternion));
    const euler = new THREE.Euler().setFromQuaternion(camera.quaternion);
    await Promise.all([
      moveTo(bookView.position, destination, 1.4),
      moveTo(bookView.rotation, euler, 1.4),
      moveTo(
        bookView.scale,
        new THREE.Vector3(readerScale(), readerScale(), readerScale()),
        1.4,
      ),
    ]);
    phase = "READING";
    document.body.classList.add("reading");
    $("reader").classList.add("show");
    $("readerTitle").textContent = b.title;
    $("bookLocation").textContent =
      `${b.bookId} / ${b.side} 面 / 第 ${b.layer} 层 / 第 ${b.slot} 本`;
    $("dragHint").textContent = "按住封面向左拖动，让故事从这里展开";
    $("openBook").textContent = "翻开书页";
    $("returnBook").disabled = false;
  }
  function readerScale() {
    return Math.min(1, (innerWidth / innerHeight) * 1.34);
  }
  function readerPosition() {
    if (!bookView) return;
    const scale = readerScale();
    bookView.scale.setScalar(scale);
    const offset = 0.7 * turn * scale;
    bookView.position
      .copy(camera.position)
      .add(
        new THREE.Vector3(offset, 0, -5.3).applyQuaternion(camera.quaternion),
      );
  }
  function setTurn(value) {
    turn = THREE.MathUtils.clamp(value, 0, 1);
    if (!hinge) return;
    hinge.rotation.y = -Math.PI * turn;
    readerPosition();
    $("openBook").textContent = turn > 0.5 ? "合上封面" : "翻开书页";
    $("dragHint").textContent =
      turn > 0.85
        ? "每一本书，都是通往另一个世界的入口。"
        : "按住封面向左拖动，让故事从这里展开";
  }
  let turnTween = null;
  function animateTurn(value) {
    turnTween?.kill();
    const state = { value: turn };
    turnTween = gsap.to(state, {
      value,
      duration: 0.65,
      ease: "power2.out",
      onUpdate: () => setTurn(state.value),
    });
  }
  function disposeBook(root) {
    factory.dispose(root);
  }
  async function returnBook() {
    if (phase !== "READING") return;
    closeChip();
    phase = "RETURNING";
    drag = null;
    turnTween?.kill();
    $("returnBook").disabled = true;
    const state = { value: turn };
    await new Promise((resolve) =>
      gsap.to(state, {
        value: 0,
        duration: 0.55,
        onUpdate: () => setTurn(state.value),
        onComplete: resolve,
      }),
    );
    $("reader").classList.remove("show");
    document.body.classList.remove("reading");
    const b = selected;
    await Promise.all([
      moveTo(bookView.position, b.origin, 1.45),
      moveTo(bookView.scale, new THREE.Vector3(0.15, 0.15, 0.15), 1.45),
      moveTo(
        bookView.rotation,
        new THREE.Vector3(0, b.side === "A" ? Math.PI / 2 : -Math.PI / 2, 0),
        1.45,
      ),
    ]);
    disposeBook(bookView);
    bookView = null;
    hinge = null;
    environment.shelfBooks.setVisible(b, true);
    if (route) {
      scene.remove(route);
      route.geometry.dispose();
      route = null;
    }
    await moveTo(
      orb.position,
      new THREE.Vector3(anchors[b.shelf - 1], 1.8, 2),
      0.65,
    );
    await moveTo(orb.position, home, 1.4);
    orbit.angle = 0.44;
    orbit.elevation = 0.65;
    orbit.radius = 26;
    const endFocus = new THREE.Vector3(0, 0, -1.2);
    const endPos = new THREE.Vector3(
      Math.sin(0.44) * Math.cos(0.65) * 26,
      Math.sin(0.65) * 26,
      -1.2 + Math.cos(0.44) * Math.cos(0.65) * 26,
    );
    await cameraTo(endPos, endFocus, 1);
    phase = "IDLE";
    selected = null;
    awakeUntil = 0;
    $("voiceTitle").textContent = "说一声「小和」，开启一段探索";
    $("locationText").textContent = "前台服务区 · 小和待命中";
    bubble("书已归位，小和在这里等你。");
  }
  const raycaster = new THREE.Raycaster(),
    pointer = new THREE.Vector2();
  let orbitDrag = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (chipView) return;
    if (e.button !== 0) return;
    if (phase === "READING") {
      pointer.set(
        (e.clientX / innerWidth) * 2 - 1,
        1 - (e.clientY / innerHeight) * 2,
      );
      raycaster.setFromCamera(pointer, camera);
      if (!raycaster.intersectObject(bookView, true).length) return;
      turnTween?.kill();
      drag = { x: e.clientX, start: turn, id: e.pointerId };
      canvas.setPointerCapture(e.pointerId);
    } else if (phase === "IDLE") {
      orbitDrag = { x: e.clientX, y: e.clientY };
      canvas.setPointerCapture(e.pointerId);
    }
  });
  canvas.addEventListener("pointermove", (e) => {
    if (drag && phase === "READING")
      setTurn(
        drag.start + (drag.x - e.clientX) / Math.min(330, innerWidth * 0.43),
      );
    else if (orbitDrag && phase === "IDLE") {
      orbit.angle -= (e.clientX - orbitDrag.x) * 0.005;
      orbit.elevation = THREE.MathUtils.clamp(
        orbit.elevation + (e.clientY - orbitDrag.y) * 0.003,
        0.2,
        1.2,
      );
      orbitDrag = { x: e.clientX, y: e.clientY };
      updateCamera();
    }
  });
  function release() {
    if (drag && phase === "READING") animateTurn(turn > 0.38 ? 1 : 0);
    drag = null;
    orbitDrag = null;
  }
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("lostpointercapture", release);
  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      if (phase !== "IDLE") return;
      orbit.radius = THREE.MathUtils.clamp(
        orbit.radius + e.deltaY * 0.016,
        12,
        38,
      );
      updateCamera();
    },
    { passive: false },
  );
  $("openBook").onclick = () => {
    if (phase === "READING") animateTurn(turn > 0.5 ? 0 : 1);
  };
  $("returnBook").onclick = returnBook;
  $("home").onclick = () => {
    if (phase === "IDLE") {
      orbit.angle = 0.44;
      orbit.elevation = 0.65;
      orbit.radius = 26;
      focus.set(0, 0, -1.2);
      updateCamera();
    }
  };
  $("sound").onclick = () => {
    speakEnabled = !speakEnabled;
    $("sound").style.background = speakEnabled ? "#adc5ad" : "#f9fbf0cf";
    $("sound").title = speakEnabled ? "关闭语音播报" : "开启语音播报";
    $("sound").setAttribute("aria-label", $("sound").title);
    if (!speakEnabled) window.speechSynthesis?.cancel();
    notice(
      speakEnabled
        ? "语音播报已开启，建议使用耳机。"
        : "语音播报已关闭，气泡回应保持开启。",
    );
  };
  $("searchForm").onsubmit = (e) => {
    e.preventDefault();
    const text = $("query").value.trim();
    if (text) {
      $("transcript").textContent = "输入：" + text;
      processText(text, true);
      $("query").value = "";
    }
  };
  document
    .querySelectorAll("[data-query]")
    .forEach((el) => (el.onclick = () => processText(el.dataset.query, true)));
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input")) return;
    if (chipView) { if(e.key === 'Escape') closeChip(); return; }
    if (e.key === "Escape" && phase === "READING") returnBook();
    if (e.key === "ArrowLeft" && phase === "READING") animateTurn(1);
    if (e.key === "ArrowRight" && phase === "READING") animateTurn(0);
  });
  window.addEventListener("resize", () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
    if (phase === "READING") readerPosition();
    positionChip();
  });
  const clock = new THREE.Clock();
  const projected = new THREE.Vector3();
  function frame() {
    requestAnimationFrame(frame);
    const time = clock.getElapsedTime();
    coreMaterial.uniforms.time.value = time;
    coreMaterial.uniforms.boost.value = navigation.pulse;
    core.position.y = Math.sin(time * 1.8) * 0.045;
    const size =
      1 +
      Math.sin(time * 2) * 0.045 +
      navigation.pulse * (0.4 + Math.sin(time * 12) * 0.1);
    core.scale.setScalar(size);
    glow.scale.setScalar(1.25 + navigation.pulse * 0.7);
    rings.forEach((r, i) => {
      r.rotation.y = time * (0.35 + i * 0.13);
      r.rotation.z = time * 0.2 + i;
      r.scale.setScalar(
        1 + navigation.pulse * ((time * 1.5 + i * 0.3) % 1) * 2,
      );
      r.material.opacity = 0.45 + navigation.pulse * 0.3;
    });
    projected
      .copy(orb.position)
      .add(new THREE.Vector3(0, 0.63, 0))
      .project(camera);
    $("bubble").style.left = (projected.x * 0.5 + 0.5) * innerWidth + "px";
    $("bubble").style.top = (-projected.y * 0.5 + 0.5) * innerHeight + "px";
    $("bubble").style.visibility = projected.z > 1 ? "hidden" : "visible";
    if (awakeUntil && Date.now() > awakeUntil) {
      awakeUntil = 0;
      if (phase === "IDLE") {
        $("bubble").classList.remove("show");
        $("voiceTitle").textContent = "说一声「小和」，开启一段探索";
      }
    }
    renderer.render(scene, camera);
  }
  frame();
  $("loading").style.display = "none";
  // Read-only diagnostics plus the exact same text dispatcher used by real ASR.
  window.libraryDebug = {
    getState: () => ({
      phase,
      turn,
      ...speech.getState(),
      modelLoaded: environment.loaded,
      modelMeshes: environment.meshes,
      book: selected?.title,
      orb: orb.position.toArray(),
      shelves: 5,
      interactiveBooks: books.length,
      staticBooks: environment.staticBooks,
    }),
    processText,
    books: books.map(({ mesh, origin, ...b }) => b),
  };
}
