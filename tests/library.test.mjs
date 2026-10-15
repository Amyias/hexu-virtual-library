import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { books } from "../src/data/catalog.js";
import { findBook as findInstalledBook, wakeRE } from "../src/voice/intent.js";
import { createSpeech } from "../src/voice/speech.js";
import { probeServerAsr } from "../src/voice/server-asr.js";
import { probeUnderstand, understand } from "../src/voice/understand.js";

import { readingBooks } from "./fixtures/books.mjs";
import { orderedShelfSlots } from "../src/data/shelf-slots.js";
import { deferredSlotIds } from "../src/data/catalog.js";
import { createHash } from "node:crypto";
const findBook = (text) => findInstalledBook(text, readingBooks);

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

test("every catalogued volume stands spine-out in its bay at the standard size", () => {
  // Blender envelope: each shelf is 1m (X) x 2m (Y) x 8m (Z), centred on the anchors. Each face
  // is a bookcase with a 300 mm deep cavity and a solid back panel whose inner face stands
  // 200 mm from the shelf centre plane. A volume is shelved spine to the aisle, so its
  // fore-edge rests on that panel and the row is packed along the spine — the thickness axis.
  // worldPosition is the volume's centre; every volume is the template's 216 x 306 x 26 mm.
  const centres = [-6, -3, 0, 3, 6];
  const posts = [-8.75, -6.8, -4.8, -2.8, -0.85];
  const post = 0.1;
  const halfPost = post / 2;
  const clear = 0.003;
  const width = 0.216; // cover width: how far the volume reaches into the shelf
  const height = 0.306;
  const thickness = 0.026; // cover to cover: the spine's width, the axis a row packs along
  const boardTops = [0.09, 0.535, 1.035, 1.535];
  const backFace = 0.2; // the panel face the fore-edge rests on, from the shelf centre plane
  const lip = 0.4955; // the brass lip at the shelf mouth
  const slots = new Set();
  const perFace = new Map();
  const perBay = new Map();
  for (const b of books) {
    const slotKey = [b.shelf, b.side, b.layer, b.slot].join(":");
    assert.ok(!slots.has(slotKey), "duplicate slot " + slotKey);
    slots.add(slotKey);
    assert.ok(b.slot >= 1, `${b.bookId} has no slot`);
    // Every volume is the template's own size. A varied shelf was tried and rejected: a
    // library reads as a library when its volumes match, and a wider volume also pushed the
    // interactive book out of the reader's frame, which hid its cover.
    assert.equal(b.widthScale, 1, `${b.bookId} is not the standard cover width`);
    assert.equal(b.heightScale, 1, `${b.bookId} is not the standard height`);
    assert.equal(b.depthScale, 1, `${b.bookId} is not the standard spine width`);

    const [x, y, z] = b.worldPosition;
    const centre = centres[b.shelf - 1];
    const sign = b.side === "A" ? 1 : -1;
    // The fore-edge rests on the back panel: the root stands half a depth out from that face.
    assert.ok(
      Math.abs(x - sign * ((width * b.widthScale) / 2) - (centre + sign * backFace)) < 1e-9,
      `${b.bookId} does not rest on the back panel`,
    );
    // The volume stands on the board: centre height = board top + half the scaled book.
    assert.ok(
      Math.abs(y - (boardTops[b.layer - 1] + (height * b.heightScale) / 2)) < 1e-6,
      `${b.bookId} does not rest on layer ${b.layer}`,
    );
    const half = (thickness * b.depthScale) / 2;
    // The spine, which is what a reader sees, has to stay inside the shelf mouth.
    const spineX = x + sign * ((width * b.widthScale) / 2);
    assert.ok(
      sign * spineX < sign * (centre + sign * lip),
      `${b.bookId} pokes through the brass lip`,
    );
    assert.ok(z - half > -8.75 && z + half < -0.85, `${b.bookId} leaves the shelf`);
    for (const post of posts)
      assert.ok(
        Math.abs(z - post) > half + halfPost,
        `${b.bookId} overlaps the frame post at z=${post}`,
      );

    const face = [b.shelf, b.side, b.layer].join(":");
    const zs = perFace.get(face) ?? new Set();
    assert.ok(!zs.has(z), `${b.bookId} shares a position on ${face}`);
    zs.add(z);
    perFace.set(face, zs);
    // Which bay the book stands in, counted between the runs of frame posts.
    const bay = posts.findIndex((post, i) => z > post && z < posts[i + 1]);
    assert.ok(bay >= 0, `${b.bookId} stands between no two posts`);
    const bayKey = [b.shelf, b.side, b.layer, bay].join(":");
    const row = perBay.get(bayKey) ?? [];
    row.push({ bookId: b.bookId, z, half, size: [b.widthScale, b.heightScale, b.depthScale] });
    perBay.set(bayKey, row);
  }
  assert.equal(perFace.size, 5 * 2 * 4);
  assert.ok(books.length > 9000 && books.length < 13000, `catalogue holds ${books.length} volumes`);
  for (const [face, zs] of perFace) assert.ok(zs.size > 200, `${face} holds ${zs.size} books`);
  // Every bay carries a packed row: spines standing shoulder to shoulder, started at the left
  // frame post, with whatever is left over standing open at the end. The catalogue this
  // replaces held two books per bay, evenly spaced apart, then eight 216 mm covers.
  assert.equal(perBay.size, 5 * 2 * 4 * 4);
  for (const [key, row] of perBay) {
    assert.ok(row.length >= 40, `${key} holds only ${row.length} volumes`);
    const bay = Number(key.split(":")[3]);
    const sorted = [...row].sort((a, b) => a.z - b.z);
    assert.ok(
      Math.abs(sorted[0].z - sorted[0].half - (posts[bay] + halfPost + clear)) < 5e-4,
      `${key} does not start at its frame post`,
    );
    for (let i = 1; i < sorted.length; i++)
      assert.ok(
        Math.abs(sorted[i].z - sorted[i].half - (sorted[i - 1].z + sorted[i - 1].half)) < 5e-4,
        `${key} leaves a gap between neighbours`,
      );
    const span = posts[bay + 1] - posts[bay] - post - 2 * clear;
    const used = sorted.at(-1).z + sorted.at(-1).half - (sorted[0].z - sorted[0].half);
    assert.ok(
      used > span * 0.9 && used <= span + 5e-4,
      `${key} is ${((used / span) * 100).toFixed(0)}% full`,
    );
    // Volumes that came as a set share one size. A shelf where every neighbour differs is
    // noise, not a shelf.
    assert.ok(
      sorted.some((b, i) => i && String(b.size) === String(sorted[i - 1].size)),
      `${key} has no matched volumes`,
    );
  }
  assert.equal(books.filter((b) => b.localBookId || b.title || b.synopsis).length, 0);
});

test("exported GLB contains five shelves, texture, valid buffers and optimized meshes", () => {
  const buffer = fs.readFileSync(new URL("../public/models/hexu-library.glb", import.meta.url));
  assert.equal(buffer.readUInt32LE(0), 0x46546c67);
  assert.equal(buffer.readUInt32LE(4), 2);
  assert.equal(buffer.readUInt32LE(8), buffer.length);
  const json = JSON.parse(buffer.subarray(20, 20 + buffer.readUInt32LE(12)).toString());
  for (let n = 1; n <= 5; n++)
    assert.ok(json.nodes.some((node) => node.name?.startsWith(`Shelf_${n}__`)));
  assert.ok(json.images.length >= 6, "both wood texture sets are embedded");
  // The floor and joinery are separate materials driven by CC0 scans. All three channels have
  // to survive the export, or the surfaces fall back to flat colour in the browser — the exact
  // failure the old single stretched grain image had.
  const wood = json.materials.filter((m) => /^Oak (floor|joinery)/.test(m.name ?? ""));
  assert.equal(wood.length, 2, "floor and joinery are exported as separate materials");
  for (const material of wood) {
    const pbr = material.pbrMetallicRoughness ?? {};
    assert.ok(pbr.baseColorTexture, `${material.name} lost its albedo`);
    assert.ok(pbr.metallicRoughnessTexture, `${material.name} lost its roughness map`);
    assert.ok(material.normalTexture, `${material.name} lost its normal map`);
  }
  // Neither wood is tinted. Each scan already sits on the tone this interior wants, and a tint
  // is a multiply — which flattens the contrast of an already low-contrast scan and is what
  // makes scanned wood read as painted board. Both must keep their own tone.
  for (const material of wood) {
    const factor = material.pbrMetallicRoughness.baseColorFactor ?? [1, 1, 1, 1];
    assert.ok(
      factor.every((channel) => channel > 0.9),
      `${material.name} should keep its scan's own tone`,
    );
  }
  assert.ok(json.meshes.length < 180, "material-batched rather than thousands of objects");
  assert.ok(buffer.length < 30_000_000, "reasonable uncompressed model budget");
  const manifest = JSON.parse(
    fs.readFileSync(new URL("../public/models/manifest.json", import.meta.url)),
  );
  assert.equal(manifest.shelves.length, 5);
  // The environment exports no static filler volumes: the shelved library is instanced from the
  // spine template at runtime. The manifest's count is Blender's tally of the catalogue, so the
  // two must agree — that is what catches a catalogue regenerated without re-running the build.
  assert.equal(manifest.static_books, 0);
  assert.equal(manifest.interactive_books, 0);
  assert.equal(manifest.shelf_slot_capacity, books.length);
  assert.ok(manifest.books_per_side_layer > 200, "a face should hold a packed row");
  assert.ok(manifest.triangles < 600_000);
});

test("smart-book template exposes the parts the reader and instancing depend on", () => {
  const buffer = fs.readFileSync(new URL("../public/models/smart-book.glb", import.meta.url));
  assert.equal(buffer.readUInt32LE(0), 0x46546c67);
  const json = JSON.parse(buffer.subarray(20, 20 + buffer.readUInt32LE(12)).toString());
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
});

test("empty slots contain no preset content and preserve every existing local slot binding", () => {
  const url = new URL("../public/models/book-inventory.json", import.meta.url);
  assert.ok(fs.statSync(url).size < 1024 * 1024);
  const inventory = JSON.parse(fs.readFileSync(url, "utf8"));
  assert.equal(inventory.format, 3);
  assert.equal(inventory.books.length, books.length);
  assert.equal(inventory.named, undefined);
  assert.equal(inventory.placeholder, undefined);
  assert.ok(!fs.existsSync(new URL("../blender/demo-shelf-map.json", import.meta.url)));
  for (const query of ["三体", "计算机基础", "HX-00001", "S5-B-L4-P284"])
    assert.equal(findInstalledBook(query), undefined, "an empty slot cannot be fetched");
  const slots = orderedShelfSlots(books, deferredSlotIds);
  assert.equal(new Set(slots.map((b) => b.bookId)).size, books.length);
  // Golden digest of all 11,348 previously assignable physical IDs, in persisted slot order.
  const digest = createHash("sha256")
    .update(
      slots
        .slice(0, 11348)
        .map((b) => b.bookId)
        .join(","),
    )
    .digest("hex");
  assert.equal(digest, "f6b19a399aeaaf96cfbf8131b5eec0f58e3527bbd9a3ba41f2b7b76c03fc316a");
});

test("real books bound after startup are searchable without stale preset aliases", () => {
  const slot = { ...books[0], keys: [...books[0].keys] };
  assert.equal(findInstalledBook(slot.bookId, [slot]), undefined);
  Object.assign(slot, { title: "新导入故事", localBookId: "local-1", localAliases: ["故事别名"] });
  assert.equal(findInstalledBook("小和找新导入故事", [slot]), slot);
  assert.equal(findInstalledBook("故事别名", [slot]), slot);
  assert.equal(findInstalledBook(slot.bookId, [slot]), slot);
  assert.equal(findInstalledBook(slot.locationCode, [slot]), slot);
  assert.equal(findInstalledBook("三体", [slot]), undefined);
});

test("detailed vegetation is exported with UV leaf texture and separate shrub meshes", () => {
  const stats = JSON.parse(
    fs.readFileSync(new URL("../blender/vegetation-manifest.json", import.meta.url)),
  );
  assert.equal(stats.potted_plants, 6);
  assert.equal(stats.shrubs, 26);
  assert.equal(stats.large_leaves, 54);
  assert.ok(stats.small_leaves > 14000);
  const b = fs.readFileSync(new URL("../public/models/hexu-library.glb", import.meta.url));
  const gltf = JSON.parse(b.subarray(20, 20 + b.readUInt32LE(12)).toString());
  assert.ok(gltf.nodes.some((n) => n.name?.startsWith("08 Exterior shrubs__")));
  assert.ok(gltf.images.some((i) => i.name === "botanical-leaf"));
  const leafMaterial = gltf.materials.find((m) => m.name?.includes("Strelitzia lamina"));
  assert.ok(leafMaterial.pbrMetallicRoughness.baseColorTexture);
  assert.equal(leafMaterial.doubleSided, true);
});

test("server ASR probe stays inert when no backend is deployed", async () => {
  // The served-as-a-static-site case must keep using the Web Speech path, so the probe has to
  // fail quietly rather than throw or leave anything pending. In this process there is no
  // origin to resolve /asr/ready against, which is exactly the static case.
  assert.equal(await probeServerAsr(), null);
});

test("semantic probe and call degrade quietly without a configured model", async () => {
  // Same rule for the model layer: with nothing configured the app must fall back to the local
  // rules rather than surface an error, and an unresolvable call must come back as "none"
  // instead of throwing into the dispatcher.
  assert.equal(await probeUnderstand(), null);
  const unanswered = await understand("霍金写的那本书", "IDLE");
  assert.equal(unanswered.action, "none");
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
      lookupBook: (text) => (text.includes("狂人日记") ? { title: "狂人日记" } : findBook(text)),
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
    const multi = [{ transcript: "小何，帮我找三替" }, { transcript: "小何，帮我找三体" }];
    multi.isFinal = true;
    recognizer.onresult({ resultIndex: 1, results: [result, multi] });
    assert.deepEqual(finals[1], ["小何，帮我找三体", false, false]);
    // 诊断记录必须同时留下「听到的」与「实际采用的」，否则无法分辨是谁的错。
    const recent = voice.getState().recent;
    assert.equal(recent.at(-1).heard, "小何，帮我找三替");
    assert.equal(recent.at(-1).used, "小何，帮我找三体");
    assert.equal(recent.at(-1).candidates, 2);
    assert.equal(recent.at(-1).matched, true);
    const localResult = [
      { transcript: "小和，帮我找狂人日记" },
      { transcript: "小和，帮我找三体" },
    ];
    localResult.isFinal = true;
    recognizer.onresult({ resultIndex: 0, results: [localResult] });
    assert.deepEqual(finals.at(-1), ["小和，帮我找狂人日记", false, false]);
    assert.equal(voice.getState().recent.at(-1).matched, true);
    recognizer.onend();
    assert.equal(timers.size, 1);
    const retry = [...timers.values()][0];
    timers.clear();
    retry();
    assert.equal(recognizer.started, 2);
    // A network failure has to stay visible. The automatic restart used to reset the status to a
    // healthy "listening", which hid a speech service that was never answering at all.
    recognizer.onerror({ error: "network" });
    assert.match($("micStatus").textContent, /网络中断/);
    recognizer.onstart();
    assert.match(
      $("micStatus").textContent,
      /未响应/,
      "the restart must not mask a service that never answered",
    );
    assert.equal(voice.getState().wanted, true);
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
