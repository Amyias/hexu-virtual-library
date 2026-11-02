import * as THREE from "three";
import { books, anchors } from "./data/catalog.js";
import { probeUnderstand } from "./voice/understand.js";
import { createSpeech } from "./voice/speech.js";
import { createRuntime } from "./scene/runtime.js";
import { loadEnvironment } from "./scene/environment.js";
import { createLighting } from "./scene/lighting.js";
import { createSky } from "./scene/sky.js";
import { createCompanion } from "./scene/companion.js";
import { createBookFactory } from "./reader/book.js";
import { createLocalLibrary } from "./reader/library.js";
import { createNovelReader } from "./reader/novel.js";
import { createReadingMusic } from "./reader/music.js";
import { createPhaseMachine, IDLE, READING } from "./app/phases.js";
import { createAttention } from "./app/dialogue.js";
import { createFeedback } from "./app/feedback.js";
import { projectDialogueAnchor, placeDialogue } from "./app/project-dialogue.js";
import { createMotion } from "./app/motion.js";
import { createReaderView } from "./app/reader-view.js";
import { createJourney } from "./app/journey.js";
import { createSettingsPanel } from "./app/settings.js";
import { createConversation } from "./app/conversation.js";
import { createAssistant } from "./app/assistant.js";
import { bindInput } from "./app/input.js";
import { createGreeting } from "./app/greeting.js";

const gsap = window.gsap;

/* Wiring only. What happens lives in ./app/: the phase machine (phases.js), how an utterance is
   read (dialogue.js) and carried out (assistant.js), the walk to the shelf and back (journey.js),
   the book in hand (reader-view.js), and the input bindings (input.js). */
export async function startLibrary() {
  if (!gsap) throw new Error("GSAP 动画依赖未能加载");
  const $ = (id) => document.getElementById(id);
  const home = new THREE.Vector3(0, 1.2, 5);
  const machine = createPhaseMachine();
  const attention = createAttention();
  const feedback = createFeedback($);
  const pulse = { value: 0 }; // the companion wake gesture, 1 → 0
  let understandReady = false;
  const settings = createSettingsPanel({
    onClose: () =>
      probeUnderstand().then((info) => {
        understandReady = Boolean(info);
      }),
  });
  let library = null;

  const canvas = $("scene");
  const { renderer, scene, camera, focus, orbit, updateCamera } = createRuntime(canvas);
  $("loading").querySelector("p").textContent = "正在加载 Blender 精细模型";
  const environment = await loadEnvironment(
    scene,
    books,
    (percent) =>
      ($("loading").querySelector("p").textContent = "正在加载 Blender 模型 " + percent + "%"),
  );
  const lighting = await createLighting({ scene, renderer, root: environment.root });
  const clockText = (date) =>
    `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  const paintSky = () => {
    const button = $("sky");
    const until = sky.manualUntil;
    const label =
      (sky.night ? "切换到太阳" : "切换到月亮") +
      (until
        ? `（已手动切换，${clockText(until)} 起恢复自动）`
        : "（08:00–17:00 太阳，其余时间月亮，自动切换）");
    button.textContent = sky.night ? "☀" : "☾";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.setAttribute("aria-pressed", String(sky.night));
    document.body.classList.toggle("night", sky.night);
  };
  const sky = await createSky({
    scene,
    lighting,
    rig: lighting.rig,
    onChange({ night, automatic }) {
      paintSky();
      const until = sky.manualUntil;
      if (automatic)
        feedback.notice(night ? "17:00 到了，月亮升起，馆内灯光亮起。" : "08:00 到了，太阳升起。");
      else if (until)
        feedback.notice(
          `${night ? "已切换到月亮" : "已切换到太阳"}，${clockText(until)} 起恢复按时间自动切换。`,
        );
      else feedback.notice("已恢复按时间自动切换：08:00–17:00 太阳，其余时间月亮。");
    },
  });
  paintSky();
  $("sky").onclick = () => sky.toggle();
  const factory = createBookFactory(renderer, environment.bookTemplate);
  const companion = await createCompanion(scene, home);
  const orb = companion.root; // Navigation keeps its existing anchor contract.

  const readingMusic = createReadingMusic();
  const novelReader = createNovelReader({
    onLinger: () => assistant.offerHelp(),
    notice: feedback.notice,
    onShow: (host) => {
      readingMusic.mount(host);
      readingMusic.start();
    },
    onHide: () => readingMusic.mount(),
  });
  const readTextButton = document.createElement("button");
  readTextButton.id = "readText";
  readTextButton.className = "secondary";
  readTextButton.textContent = "阅读正文";
  $("reader").querySelector(".reader-bottom").insertBefore(readTextButton, $("inspectChip"));

  const motion = createMotion({ gsap, scene, camera, focus, home });
  const view = createReaderView({
    gsap,
    $,
    scene,
    camera,
    factory,
    machine,
    readingMusic,
    novelReader,
  });
  const journey = createJourney({
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
  });
  const conversation = createConversation({
    onSubmit: (text) => assistant.processText(text, true),
    onCancel: () => assistant.cancelPending(),
    onClear: () => assistant.clearConversation(),
  });
  /** Show where a book stands, from the library panel's 「定位书架」 or when 小和 is asked. */
  function locateOnShelf(book) {
    if (!machine.is(IDLE)) {
      feedback.notice("书已上架。请先放回当前书籍，再定位书架。");
      return false;
    }
    // Look straight into the assigned face from its aisle. At overview scale a single
    // 26 mm spine is less than a pixel wide; locating keeps it standing in its real slot.
    focus.copy(book.origin);
    Object.assign(orbit, {
      angle: book.side === "A" ? Math.PI / 2 : -Math.PI / 2,
      elevation: 0.22,
      radius: 1.55,
    });
    updateCamera();
    environment.shelfBooks.highlight(book, true);
    $("locationText").textContent =
      `《${book.title}》 · 第 ${book.shelf} 架 ${book.side} 面 · 第 ${book.layer} 层 · 第 ${book.slot} 本`;
    feedback.notice(`已定位 ${book.locationCode}，书本保留在架上；可在正文书库取阅。`);
    return true;
  }
  const assistant = createAssistant({
    conversation,
    gsap,
    $,
    machine,
    attention,
    feedback,
    journey,
    view,
    pulse,
    home,
    getLibrary: () => library,
    novelReader,
    isUnderstandReady: () => understandReady,
    readingMusic,
    actions: { setSky: (mode) => sky.choose(mode), locate: (book) => locateOnShelf(book) },
  });
  library = createLocalLibrary({
    books,
    notice: feedback.notice,
    onBind: (book) => environment.shelfBooks.setVisible(book, true),
    onLocate: locateOnShelf,
    onSelect(book) {
      if (machine.is(IDLE)) assistant.present(book, "正文已在本地书库，正在为您定位。");
      else if (machine.is(READING) && journey.selected?.localBookId === book.localBookId)
        novelReader.show();
      else feedback.notice("正文已上架。请先放回当前书籍，再从正文书库取阅。");
    },
  });
  const speech = createSpeech({
    $,
    notice: feedback.notice,
    wake: assistant.wake,
    processText: assistant.processText,
    getPhase: () => machine.phase,
    lookupBook: assistant.lookup,
    // 「小和」 said over 小和's own voice stops the reply being spoken and written.
    interrupt: assistant.cancelPending,
  });
  bindInput({
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
    petRoot: orb,
  });

  /* A model may be configured on the deployment for phrasing the local rules cannot read.
     Probing is best-effort and silent: without one, every request still goes through the rules,
     which is why this can never make the app worse. */
  probeUnderstand().then((info) => {
    if (!info) return;
    understandReady = true;
    feedback.notice(`小和的模型已配置（${info.model}），可以自由提问或自然语言找书`);
  });
  window.addEventListener("focus", () => {
    probeUnderstand().then((info) => {
      understandReady = Boolean(info);
    });
  });
  /* The packaged service checks and applies updates automatically; the page shows its status. */
  fetch("/update/status", { cache: "no-store" })
    .then((response) => (response.ok ? response.json() : null))
    .then((info) => {
      if (info && info.state === "update-available")
        feedback.notice(`发现新版本（${info.reason}），将自动下载、校验并重启。`);
    })
    .catch(() => {});

  // How long the reader has left 小和 alone: it starts amusing itself after a while.
  let lastActivity = performance.now();
  for (const type of ["pointerdown", "keydown", "wheel"])
    addEventListener(type, () => (lastActivity = performance.now()), {
      capture: true,
      passive: true,
    });
  const clock = new THREE.Clock();
  const projected = new THREE.Vector3();
  const bubbleAnchor = new THREE.Vector3(0, 0.63, 0);
  const petVisual = orb.getObjectByName("CompanionMotion");
  const petBox = new THREE.Box3(),
    petCorner = new THREE.Vector3();
  let petBounds = null,
    dialoguePlacement = "above";
  function frame() {
    requestAnimationFrame(frame);
    const time = clock.getElapsedTime();
    if (!machine.is(IDLE) || pulse.value > 0.02 || feedback.getState().typing)
      lastActivity = performance.now();
    companion.update({
      time,
      pulse: pulse.value,
      phase: machine.phase,
      camera,
      idleFor: (performance.now() - lastActivity) / 1000,
      night: sky.night,
    });
    sky.update({ time, camera });
    projectDialogueAnchor(camera, orb.position, bubbleAnchor, projected);
    petVisual.updateWorldMatrix(true, true);
    petBox.setFromObject(petVisual);
    petBounds = { left: Infinity, right: -Infinity, top: Infinity, bottom: -Infinity };
    for (let i = 0; i < 8; i++) {
      petCorner
        .set(
          i & 1 ? petBox.max.x : petBox.min.x,
          i & 2 ? petBox.max.y : petBox.min.y,
          i & 4 ? petBox.max.z : petBox.min.z,
        )
        .project(camera);
      const x = (petCorner.x * 0.5 + 0.5) * innerWidth;
      const y = (-petCorner.y * 0.5 + 0.5) * innerHeight;
      petBounds.left = Math.min(petBounds.left, x);
      petBounds.right = Math.max(petBounds.right, x);
      petBounds.top = Math.min(petBounds.top, y);
      petBounds.bottom = Math.max(petBounds.bottom, y);
    }
    if (
      projected.z > 1 ||
      petBounds.right < 0 ||
      petBounds.left > innerWidth ||
      petBounds.bottom < 0 ||
      petBounds.top > innerHeight
    )
      petBounds = null;
    const bubble = $("bubble");
    const interactive = bubble.classList.contains("interactive");
    // Keep spoken replies visible while reading, or when the pet moves outside the camera view.
    const pinned =
      interactive &&
      (novelReader.visible ||
        library.opened ||
        !machine.is(IDLE) ||
        projected.z > 1 ||
        Math.abs(projected.x) > 1 ||
        Math.abs(projected.y) > 1);
    bubble.classList.toggle("pinned", pinned);
    const width = bubble.offsetWidth;
    const naturalHeight = bubble.querySelector(".bubble-frame").scrollHeight + 1;
    if (width && naturalHeight) {
      const position = placeDialogue({
        viewWidth: innerWidth,
        viewHeight: innerHeight,
        bubbleWidth: width,
        bubbleHeight: naturalHeight,
        anchorX: (projected.x * 0.5 + 0.5) * innerWidth,
        anchorY: (-projected.y * 0.5 + 0.5) * innerHeight,
        pet: petBounds,
        pinned,
        previous: dialoguePlacement,
      });
      dialoguePlacement = position.placement;
      bubble.classList.toggle("detached", dialoguePlacement !== "above");
      bubble.style.left = Math.round(position.left) + "px";
      bubble.style.top = Math.round(position.top) + "px";
      bubble.style.setProperty("--bubble-available-height", Math.floor(position.maxHeight) + "px");
      bubble.style.setProperty("--bubble-tail-x", position.tail + "px");
    }
    bubble.style.visibility = interactive || projected.z <= 1 ? "visible" : "hidden";
    if (attention.lapsed() && machine.is(IDLE)) {
      if (!feedback.getState().persistent) feedback.hideBubble();
      $("voiceTitle").textContent = "说一声「小和」，开启一段探索";
    }
    // The full-screen text panels keep the last scene frame; reading needs no GPU redraws.
    if (!novelReader.visible && !library.opened && !settings.opened) {
      lighting.setDynamicShadows(!machine.is(IDLE) && !machine.is(READING));
      renderer.render(scene, camera);
    }
  }
  frame();
  $("loading").style.display = "none";
  // One greeting per start, only when it would interrupt nothing.
  createGreeting({
    say: (text) => feedback.say(text),
    ready: () =>
      machine.is(IDLE) &&
      !feedback.getState().visible &&
      !library.opened &&
      !novelReader.visible &&
      !settings.opened &&
      !assistant.getChatState().busy,
  }).start();

  // Read-only diagnostics plus the exact same text dispatcher used by real ASR.
  window.libraryDebug = {
    getState: () => ({
      phase: machine.phase,
      turn: view.turn,
      ...speech.getState(),
      modelLoaded: environment.loaded,
      modelMeshes: environment.meshes,
      lighting: lighting.getState(),
      sky: sky.getState(),
      book: journey.selected?.title,
      orb: orb.position.toArray(),
      companion: companion.getState(),
      dialogue: feedback.getState(),
      chat: { ...assistant.getChatState(), ...conversation.getState() },
      settings: settings.getState(),
      petScreen: (() => {
        const point = orb.position.clone().project(camera);
        return [(point.x * 0.5 + 0.5) * innerWidth, (-point.y * 0.5 + 0.5) * innerHeight];
      })(),
      petBounds: petBounds && { ...petBounds },
      dialoguePlacement,
      shelves: 5,
      interactiveBooks: books.filter((book) => book.localBookId).length,
      shelfCapacity: books.length,
      visibleShelfBooks: environment.shelfBooks.visibleCount,
      renderedShelfSlots: environment.shelfBooks.drawCount,
      shelfView: { focus: focus.toArray(), camera: camera.position.toArray() },
      shelfHighlight: environment.shelfBooks.highlightedPosition,
      staticBooks: environment.staticBooks,
      localLibrary: library.getState(),
      novel: novelReader.getState(),
      music: readingMusic.getState(),
    }),
    processText: assistant.processText,
    get books() {
      return books.filter((book) => book.localBookId).map(({ mesh, origin, ...b }) => b);
    },
  };
}
