/* 语音验收：录音、回放评测与合成语音自检。说明见 docs/VOICE_EVAL.md。

     node tools/voice-eval.mjs record [--port 8098]   打开本机录音页，逐条录 tests/voice-eval/prompts.json
     node tools/voice-eval.mjs run [--clips 目录] [--label 名称]   回放录音并出报告
     node tools/voice-eval.mjs synth                  用本机欣然语音合成全部提示再评测，只验证流程

   录音、切段与报告都在 .cache/voice-eval/ 下（不进版本库，录音是读者本人的声音）。
   回放时每段录音按程序真实的断句规则（src/voice/server-asr.js 的 createSegmenter）切段，交给
   程序同一个识别函数，再经 decide() 与 lookupBooks() 判断，不调用大模型、不连网。 */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { books as slots } from "../src/data/catalog.js";
import { encodeWav, SEGMENT } from "../src/voice/server-asr.js";
import { readWav, segmentsOf } from "./voice-eval/audio.mjs";
import { evaluationShelf, scoreClip, summarize } from "./voice-eval/score.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const home = path.join(root, ".cache", "voice-eval");
const promptsFile = path.join(root, "tests", "voice-eval", "prompts.json");
const { prompts } = JSON.parse(fs.readFileSync(promptsFile, "utf8"));
const bound = JSON.parse(
  fs.readFileSync(path.join(root, "tests", "voice-eval", "books.json"), "utf8"),
);
const python = [path.join(root, ".cache", "venv", "Scripts", "python.exe"), "python"].find(
  (candidate) => candidate === "python" || fs.existsSync(candidate),
);

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  return index > 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

function runPython(args) {
  const result = spawnSync(
    python,
    [path.join(root, "tools", "voice-eval", "transcribe.py"), ...args],
    {
      cwd: root,
      encoding: "utf8",
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      maxBuffer: 64 * 1024 * 1024,
    },
  );
  if (result.status !== 0)
    throw new Error((result.stderr || result.stdout || "Python 失败").trim());
}

async function run(clips, label) {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 13);
  const work = path.join(home, "work", stamp);
  fs.mkdirSync(work, { recursive: true });
  const listing = [];
  const clipsById = new Map();
  const missing = [];
  for (const prompt of prompts) {
    const file = path.join(clips, prompt.id + ".wav");
    if (!fs.existsSync(file)) {
      missing.push(prompt.id);
      continue;
    }
    const samples = readWav(fs.readFileSync(file));
    const segments = segmentsOf(samples);
    for (const [index, segment] of segments.entries()) {
      const key = `${prompt.id}#${index}`;
      const target = path.join(work, `${prompt.id}-${index}.wav`);
      const wav = encodeWav(segment.samples, SEGMENT.TARGET_RATE);
      fs.writeFileSync(target, Buffer.from(await wav.arrayBuffer()));
      listing.push({ key, path: target });
      segment.key = key;
    }
    clipsById.set(prompt.id, { seconds: samples.length / SEGMENT.TARGET_RATE, segments });
  }
  if (!clipsById.size)
    throw new Error(`${clips} 里没有录音。先运行 node tools/voice-eval.mjs record`);
  fs.writeFileSync(path.join(work, "list.json"), JSON.stringify(listing));
  runPython(["transcribe", path.join(work, "list.json"), path.join(work, "out.json")]);
  const heard = JSON.parse(fs.readFileSync(path.join(work, "out.json"), "utf8"));
  fs.rmSync(work, { recursive: true, force: true });

  const shelf = evaluationShelf(slots, bound);
  const rows = prompts
    .filter((prompt) => clipsById.has(prompt.id))
    .map((prompt) => {
      const clip = clipsById.get(prompt.id);
      return scoreClip(
        prompt,
        {
          seconds: clip.seconds,
          segments: clip.segments.map((segment) => ({
            text: heard[segment.key]?.text || "",
            tailMs: segment.tailMs,
            recogMs: Math.round((heard[segment.key]?.seconds || 0) * 1000),
          })),
        },
        shelf,
      );
    });
  const used = prompts.filter((prompt) => clipsById.has(prompt.id));
  const summary = summarize(rows, used);
  const report = {
    label,
    clips: path.relative(root, clips),
    createdAt: new Date().toISOString(),
    summary,
    missing,
    rows,
  };
  const out = path.join(home, `report-${label}-${stamp}.json`);
  fs.writeFileSync(out, JSON.stringify(report, null, 2));

  const percent = (value) => (value === null ? "—" : (value * 100).toFixed(1) + "%");
  console.log(
    `语音验收（${label}）：${rows.length} 条录音${missing.length ? `，缺 ${missing.length} 条` : ""}`,
  );
  console.log(`  唤醒召回率      ${percent(summary.wakeRecall)}`);
  console.log(
    `  误唤醒          ${summary.falseWakes} 次（约 ${summary.falseWakesPerHour ?? "—"} 次/小时）`,
  );
  console.log(`  意图正确率      ${percent(summary.intentAccuracy)}`);
  console.log(`  找书准确率      ${percent(summary.findAccuracy)}`);
  console.log(`  字错率 CER      ${percent(summary.characterErrorRate)}`);
  console.log(`  断句段数不符    ${summary.segmentationMismatches} 条`);
  console.log(
    `  句尾延迟        P50 ${summary.latencyMs.p50 ?? "—"} ms，P95 ${summary.latencyMs.p95 ?? "—"} ms`,
  );
  for (const [name, entry] of Object.entries(summary.categories))
    console.log(`  · ${name}：${entry.correct}/${entry.clips}`);
  const wrong = rows.filter((row) => !row.correct || !row.wakeOk);
  if (wrong.length) console.log("未通过：");
  for (const row of wrong)
    console.log(
      `  ${row.id}  听到「${row.heard.join(" | ")}」→ ${row.outcome.type}${row.outcome.book ? " " + row.outcome.book : ""}`,
    );
  console.log(`报告：${path.relative(root, out)}`);
}

/* --- recording page ----------------------------------------------------------------------- */

const STATIC = {
  "/": ["tools/voice-eval/recorder.html", "text/html; charset=utf-8"],
  "/src/voice/server-asr.js": ["src/voice/server-asr.js", "text/javascript; charset=utf-8"],
};

function record(port) {
  const clips = path.join(home, "clips");
  fs.mkdirSync(clips, { recursive: true });
  const ids = new Set(prompts.map((prompt) => prompt.id));
  const origin = `http://127.0.0.1:${port}`;
  const server = http.createServer((request, response) => {
    const url = new URL(request.url, origin);
    const send = (status, body, type = "application/json; charset=utf-8") => {
      response.writeHead(status, { "Content-Type": type, "Cache-Control": "no-store" });
      response.end(body);
    };
    if (request.method === "GET" && STATIC[url.pathname]) {
      const [file, type] = STATIC[url.pathname];
      return send(200, fs.readFileSync(path.join(root, file)), type);
    }
    if (request.method === "GET" && url.pathname === "/prompts") {
      const done = prompts.filter((prompt) => fs.existsSync(path.join(clips, prompt.id + ".wav")));
      return send(200, JSON.stringify({ prompts, done: done.map((prompt) => prompt.id) }));
    }
    const match = url.pathname.match(/^\/clips\/([a-z]+-\d+)\.wav$/);
    if (!match || !ids.has(match[1])) return send(404, '{"error":"没有这条"}');
    const file = path.join(clips, match[1] + ".wav");
    if (request.method === "GET") {
      if (!fs.existsSync(file)) return send(404, '{"error":"还没录"}');
      return send(200, fs.readFileSync(file), "audio/wav");
    }
    // Only this page may save: another site open in the same browser must not write here.
    if (request.method !== "POST" || request.headers.origin !== origin)
      return send(403, '{"error":"拒绝"}');
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size <= 8_000_000) chunks.push(chunk);
    });
    request.on("end", () => {
      const body = Buffer.concat(chunks);
      if (size > 8_000_000 || body.toString("ascii", 0, 4) !== "RIFF")
        return send(400, '{"error":"录音无效"}');
      fs.writeFileSync(file, body);
      send(200, '{"ok":true}');
    });
  });
  server.listen(port, "127.0.0.1", () => {
    console.log(`录音页：${origin}/  （录音保存在 ${path.relative(root, clips)}，按 Ctrl+C 结束）`);
  });
}

const command = process.argv[2] || "run";
if (command === "record") record(Number(option("--port", "8098")));
else if (command === "run")
  await run(path.resolve(option("--clips", path.join(home, "clips"))), option("--label", "real"));
else if (command === "synth") {
  const target = path.join(home, "synthetic");
  console.log("正在用本机欣然语音合成全部提示…");
  runPython(["synth", promptsFile, target]);
  await run(target, "synthetic");
} else {
  console.error("用法：node tools/voice-eval.mjs record | run | synth");
  process.exit(2);
}
