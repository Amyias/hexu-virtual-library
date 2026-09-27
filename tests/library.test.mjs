import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { books } from "../src/data/catalog.js";
import { findBook, wakeRE } from "../src/voice/intent.js";
import { createSpeech } from "../src/voice/speech.js";

test("wake aliases and Chinese/English normalization", () => {
  for (const word of ["小和", "小何", "肖和", "小荷", "小禾", "小鹤", "xiao he", "XIAO HE"])
    assert.ok(wakeRE.test(word));
  assert.equal(findBook("小和，帮我找《三体》").title, "三体");
  assert.equal(findBook("计算机基础在哪里").shelf, 1);
  assert.equal(findBook("我想找一本关于人工智能的书").layer, 3);
  assert.equal(findBook("时间简史").side, "B");
  assert.equal(findBook("一本不存在的书"), undefined);
});

test("tolerates a one-character recognition slip without matching unrelated words", () => {
  // 单字同音错字：编辑距离为 1，书名 3 字以上时应能找回。
  assert.equal(findBook("时间减史").title, "时间简史");
  assert.equal(findBook("人类减史").title, "人类简史");
  // 查询只是书名的一段。
  assert.equal(findBook("计算机").title, "计算机基础");
  assert.equal(findBook("时间").title, "时间简史");
  // 单字查询不参与近似匹配，否则会大面积误命中。
  assert.equal(findBook("三"), undefined);
  assert.equal(findBook("书"), undefined);
  // 二字书名只做精确匹配。编辑距离分不出同音与不同音——「题」「体」同音而
  // 「国」「体」不同音，距离却都是 1——放开「三体」会让下列常用词全部误命中。
  // 「三题」这类二字错字改由识别器的候选列表救回，比放宽距离更准。
  for (const word of ["身体", "全体", "团体", "三国", "三千", "沙滩", "沙发", "沙子"])
    assert.equal(findBook(word), undefined, word + " 不应命中任何馆藏");
  // 差得较远的输入仍须无匹配。
  for (const word of ["计算机图形学", "今天天气怎么样", "帮我找本书", "放回书架"])
    assert.equal(findBook(word), undefined, word + " 不应命中任何馆藏");
});

test("every catalogued chip rests on its board inside a bay, 8 per face and layer", () => {
  const input = JSON.parse(
    fs.readFileSync(
      new URL("../blender/catalog.json", import.meta.url),
      "utf8",
    ),
  );
  assert.deepEqual(books, input);
  // Blender envelope: each shelf is 1m (X) x 2m (Y) x 8m (Z), centred on the anchors.
  // Each face is a bookcase with a 300 mm deep cavity; slot numbers are a bay-relative
  // index 1..8 and real placement lives in worldPosition.
  const centres = [-6, -3, 0, 3, 6];
  const posts = [-8.75, -6.8, -4.8, -2.8, -0.85];
  const halfPost = 0.05;
  const halfBook = 0.216 / 2;
  const halfHeight = 0.306 / 2;
  const boardTops = [0.09, 0.535, 1.035, 1.535];
  const backFace = 0.2; // the face a book leans on, from the shelf centre plane
  const rearBoard = 0.0126; // book root to its rear board, off smart-book.glb
  const thickness = 0.0258; // book depth, off smart-book.glb
  const slots = new Set();
  const perFace = new Map();
  for (const b of books) {
    const slotKey = [b.shelf, b.side, b.layer, b.slot].join(":");
    assert.ok(!slots.has(slotKey), "duplicate slot " + slotKey);
    slots.add(slotKey);
    assert.ok(b.slot >= 1 && b.slot <= 8, `${b.bookId} is outside the 8-per-face grid`);

    const [x, y, z] = b.worldPosition;
    const centre = centres[b.shelf - 1];
    const sign = b.side === "A" ? 1 : -1;
    // The rear board must touch the back panel face, which is what holds the volume up.
    assert.ok(
      Math.abs(x - sign * rearBoard - (centre + sign * backFace)) < 1e-9,
      `${b.bookId} does not lean on the back panel`,
    );
    // The volume stands on the board: centre height = board top + half the book height.
    assert.ok(
      Math.abs(y - (boardTops[b.layer - 1] + halfHeight)) < 1e-9,
      `${b.bookId} does not rest on layer ${b.layer}`,
    );
    // Entirely inside its own bookcase, clear of the brass lip and the frame posts.
    const outerX = x + sign * (thickness - rearBoard);
    const lipX = centre + sign * 0.4955;
    assert.ok(sign * outerX < sign * lipX, `${b.bookId} pokes through the brass lip`);
    assert.ok(z - halfBook > -8.75 && z + halfBook < -0.85, `${b.bookId} leaves the shelf`);
    for (const post of posts)
      assert.ok(
        Math.abs(z - post) > halfBook + halfPost,
        `${b.bookId} overlaps the frame post at z=${post}`,
      );

    const face = [b.shelf, b.side, b.layer].join(":");
    const zs = perFace.get(face) ?? new Set();
    assert.ok(!zs.has(z), `${b.bookId} shares a position on ${face}`);
    zs.add(z);
    perFace.set(face, zs);
  }
  assert.equal(books.length, 320);
  assert.equal(perFace.size, 5 * 2 * 4);
  for (const [face, zs] of perFace) assert.equal(zs.size, 8, `${face} holds ${zs.size} books`);
  assert.equal(books.filter((b) => !b.placeholder).length, 12);
});

test("exported GLB contains five shelves, texture, valid buffers and optimized meshes", () => {
  const buffer = fs.readFileSync(
    new URL("../public/models/hexu-library.glb", import.meta.url),
  );
  assert.equal(buffer.readUInt32LE(0), 0x46546c67);
  assert.equal(buffer.readUInt32LE(4), 2);
  assert.equal(buffer.readUInt32LE(8), buffer.length);
  const json = JSON.parse(
    buffer.subarray(20, 20 + buffer.readUInt32LE(12)).toString(),
  );
  for (let n = 1; n <= 5; n++)
    assert.ok(json.nodes.some((node) => node.name?.startsWith(`Shelf_${n}__`)));
  assert.ok(json.images.length >= 1, "wood-grain image is embedded");
  assert.ok(
    json.meshes.length < 180,
    "material-batched rather than thousands of objects",
  );
  assert.ok(buffer.length < 30_000_000, "reasonable uncompressed model budget");
  const manifest = JSON.parse(
    fs.readFileSync(new URL("../public/models/manifest.json", import.meta.url)),
  );
  assert.equal(manifest.shelves.length, 5);
  // Every shelf book is one of the 320 instanced interactive copies built from
  // smart-book.glb, so the merged environment exports no static filler volumes.
  assert.equal(manifest.static_books, 0);
  assert.equal(manifest.interactive_books, 320);
  assert.equal(manifest.books_per_side_layer, 8);
  assert.ok(manifest.triangles < 600_000);
});

test("smart-book template exposes the parts the reader and instancing depend on", () => {
  const buffer = fs.readFileSync(
    new URL("../public/models/smart-book.glb", import.meta.url),
  );
  assert.equal(buffer.readUInt32LE(0), 0x46546c67);
  const json = JSON.parse(
    buffer.subarray(20, 20 + buffer.readUInt32LE(12)).toString(),
  );
  const names = json.nodes.map((node) => node.name);
  for (const part of [
    "BookTemplate",
    "FrontHinge",
    "FrontCover_top",
    "FrontCover_bottom",
    "RearBoard",
    "RoundedSpine",
    "PageBlock",
    "RecessFloor",
    "ChipWindow",
  ])
    assert.ok(names.includes(part), `smart-book.glb is missing ${part}`);
  // The front cover is hinged on a separate node, which is what makes it swing open.
  const hinge = json.nodes.find((node) => node.name === "FrontHinge");
  assert.ok(Array.isArray(hinge.children) && hinge.children.length > 0);
  assert.ok(
    json.materials.some((m) => m.name === "Book | fine woven cover"),
    "cloth cover material drives the per-instance shelf colours",
  );
  // All three generated inventory copies must stay identical.
  assert.deepEqual(
    JSON.parse(
      fs.readFileSync(
        new URL("../public/models/book-inventory.json", import.meta.url),
      ),
    ),
    JSON.parse(
      fs.readFileSync(new URL("../blender/catalog.json", import.meta.url)),
    ),
  );
});

test("detailed vegetation is exported with UV leaf texture and separate shrub meshes", () => {
  const stats = JSON.parse(fs.readFileSync(new URL('../blender/vegetation-manifest.json', import.meta.url)));
  assert.equal(stats.potted_plants, 6);
  assert.equal(stats.shrubs, 26);
  assert.equal(stats.large_leaves, 54);
  assert.ok(stats.small_leaves > 14000);
  const b = fs.readFileSync(new URL('../public/models/hexu-library.glb', import.meta.url));
  const gltf = JSON.parse(b.subarray(20, 20 + b.readUInt32LE(12)).toString());
  assert.ok(gltf.nodes.some(n => n.name?.startsWith('08 Exterior shrubs__')));
  assert.ok(gltf.images.some(i => i.name === 'botanical-leaf'));
  const leafMaterial = gltf.materials.find(m => m.name?.includes('Strelitzia lamina'));
  assert.ok(leafMaterial.pbrMetallicRoughness.baseColorTexture);
  assert.equal(leafMaterial.doubleSided, true);
});

test("real recognizer adapter preserves interim wake, final intent, restart and permission stop", () => {
  const elements = {},
    listeners = {},
    timers = new Map();
  let id = 0,
    recognizer;
  const original = {
    window: globalThis.window,
    document: globalThis.document,
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
  };
  class Recognition {
    constructor() {
      recognizer = this;
    }
    start() {
      this.started = (this.started || 0) + 1;
    }
    abort() {
      this.onend();
    }
  }
  const $ = (name) =>
    (elements[name] ??= {
      textContent: "",
      className: "",
      classList: {
        toggle() {},
        contains() {
          return false;
        },
      },
    });
  globalThis.window = {
    SpeechRecognition: Recognition,
    isSecureContext: true,
    addEventListener() {},
  };
  globalThis.document = {
    hidden: false,
    body: { classList: { toggle() {} } },
    addEventListener(name, fn) {
      listeners[name] = fn;
    },
  };
  globalThis.setTimeout = (fn) => {
    timers.set(++id, fn);
    return id;
  };
  globalThis.clearTimeout = (key) => timers.delete(key);
  let wakes = 0,
    finals = [];
  try {
    const voice = createSpeech({
      $,
      notice() {},
      wake() {
        wakes++;
      },
      processText(...args) {
        finals.push(args);
      },
      getPhase: () => "IDLE",
    });
    $("micButton").onclick();
    recognizer.onstart();
    assert.equal(voice.getState().running, true);
    assert.equal(recognizer.continuous, true);
    assert.equal(recognizer.interimResults, true);
    assert.ok(recognizer.maxAlternatives > 1, "候选数必须大于 1，否则没有可用的候选");
    const result = [{ transcript: "小何，帮我找三体" }];
    result.isFinal = false;
    recognizer.onresult({ resultIndex: 0, results: [result] });
    recognizer.onresult({ resultIndex: 0, results: [result] });
    assert.equal(wakes, 1);
    assert.equal(finals.length, 0);
    result.isFinal = true;
    recognizer.onresult({ resultIndex: 0, results: [result] });
    assert.deepEqual(finals, [["小何，帮我找三体", false, true]]);
    // 首选听成同音错字时，必须靠较低候选把这句话救回来，而不是整句丢掉。
    const multi = [
      { transcript: "小何，帮我找三替" },
      { transcript: "小何，帮我找三体" },
    ];
    multi.isFinal = true;
    recognizer.onresult({ resultIndex: 1, results: [result, multi] });
    assert.deepEqual(finals[1], ["小何，帮我找三体", false, false]);
    // 诊断记录必须同时留下「听到的」与「实际采用的」，否则无法分辨是谁的错。
    const recent = voice.getState().recent;
    assert.equal(recent.at(-1).heard, "小何，帮我找三替");
    assert.equal(recent.at(-1).used, "小何，帮我找三体");
    assert.equal(recent.at(-1).candidates, 2);
    assert.equal(recent.at(-1).matched, true);
    recognizer.onend();
    assert.equal(timers.size, 1);
    const retry = [...timers.values()][0];
    timers.clear();
    retry();
    assert.equal(recognizer.started, 2);
    recognizer.onstart();
    recognizer.onerror({ error: "not-allowed" });
    assert.equal(voice.getState().wanted, false);
    recognizer.onend();
    assert.equal(timers.size, 0);
    voice.stop();
  } finally {
    Object.assign(globalThis, original);
  }
});
