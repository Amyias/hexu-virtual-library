/* 语音验收的评分：把每条录音切出的识别文字交给与程序相同的 decide() 与 lookupBooks()，
   再与 prompts.json 里的理想结果比较。纯函数，不碰麦克风、模型或网络，便于单测。 */
import { decide } from "../../src/app/dialogue.js";
import { lookupBooks } from "../../src/reader/library.js";
import { wakeRE } from "../../src/voice/intent.js";

/** The evaluation's own shelf: empty slots with the books of books.json bound to them, so the
 *  result never depends on what the reader's real library happens to hold. */
export function evaluationShelf(slots, bound) {
  const byId = new Map(bound.map((book) => [book.bookId, book]));
  return slots.map((slot) => {
    const book = byId.get(slot.bookId);
    return book
      ? { ...slot, title: book.title, author: book.author, localBookId: book.bookId }
      : slot;
  });
}

/** Run one recording's segment texts through the dialogue as the program would: 「小和」 alone
 *  opens the waiting window, so a request in the next segment needs no wake word. The model is
 *  configured (understand: true) and the reading library is present (fullText: true), as in the
 *  desktop program; routes to the model are scored as routes, nothing is sent. */
export function replay(prompt, texts, shelf) {
  const phase = prompt.phase || "IDLE";
  const lookup = (text) => lookupBooks(text, [], shelf);
  let awake = false;
  let heard = false;
  let outcome = { type: "ignore" };
  for (const text of texts) {
    if (!text) continue;
    heard ||= wakeRE.test(text);
    const decision = decide(text, { phase, awake, lookup, fullText: true, understand: true });
    if (decision.type === "ignore") continue;
    if (decision.type === "wake-only") awake = true;
    outcome = decision;
  }
  return { wake: heard, outcome };
}

/** Whether a replayed outcome is what the prompt expects. */
export function matches(expect, outcome) {
  if (outcome.type !== expect.type) return false;
  if (expect.book && outcome.book?.title !== expect.book) return false;
  if (expect.books) {
    const titles = (outcome.books || []).map((book) => book.title).sort();
    if (JSON.stringify(titles) !== JSON.stringify([...expect.books].sort())) return false;
  }
  if (expect.command && outcome.command !== expect.command) return false;
  return true;
}

const DIGITS = {
  零: "0",
  一: "1",
  二: "2",
  三: "3",
  四: "4",
  五: "5",
  六: "6",
  七: "7",
  八: "8",
  九: "9",
};

/** Text as the character error rate compares it: no spaces or punctuation, lower case, and
 *  Chinese digits as Arabic ones, since the recogniser writes 「零二二七三」 as 02273. */
export function plain(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[\s，。！？、,.!?：:；;“”"'《》·\-—…]/g, "")
    .replace(/[零一二三四五六七八九]/g, (digit) => DIGITS[digit]);
}

export function editDistance(a, b) {
  const x = [...a];
  const y = [...b];
  let previous = Array.from({ length: y.length + 1 }, (_, i) => i);
  for (let i = 1; i <= x.length; i++) {
    const current = [i];
    for (let j = 1; j <= y.length; j++)
      current[j] = Math.min(
        previous[j] + 1,
        current[j - 1] + 1,
        previous[j - 1] + (x[i - 1] === y[j - 1] ? 0 : 1),
      );
    previous = current;
  }
  return previous[y.length];
}

export function percentile(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)];
}

const ratio = (part, whole) => (whole ? Math.round((part / whole) * 1000) / 1000 : null);

/** One clip's result: { prompt, seconds, segments: [{ text, tailMs, recogMs }] } → scored row. */
export function scoreClip(prompt, clip, shelf) {
  const texts = clip.segments.map((segment) => segment.text);
  const { wake, outcome } = replay(prompt, texts, shelf);
  const reference = plain(prompt.say.join(""));
  return {
    id: prompt.id,
    category: prompt.category,
    noise: Boolean(prompt.noise),
    seconds: clip.seconds,
    heard: texts,
    expectedSegments: prompt.say.length,
    segments: clip.segments.length,
    wake,
    wakeOk: wake === prompt.expect.wake,
    outcome: {
      type: outcome.type,
      book: outcome.book?.title,
      books: outcome.books?.map((book) => book.title),
      command: outcome.command,
    },
    correct: matches(prompt.expect, outcome),
    edits: editDistance(reference, plain(texts.join(""))),
    referenceChars: [...reference].length,
    latencyMs: clip.segments.map((segment) => segment.tailMs + segment.recogMs),
  };
}

/** The numbers the report leads with, from scored rows and their prompts. */
export function summarize(rows, prompts) {
  const expect = new Map(prompts.map((prompt) => [prompt.id, prompt.expect]));
  const shouldWake = rows.filter((row) => expect.get(row.id).wake);
  const shouldNot = rows.filter((row) => !expect.get(row.id).wake);
  const finding = rows.filter((row) => expect.get(row.id).book || expect.get(row.id).books);
  const negativeHours = shouldNot.reduce((sum, row) => sum + row.seconds, 0) / 3600;
  const falseWakes = shouldNot.filter((row) => row.wake).length;
  const latencies = rows.filter((row) => expect.get(row.id).wake).flatMap((row) => row.latencyMs);
  const categories = {};
  for (const row of rows) {
    const entry = (categories[row.category] ||= { clips: 0, correct: 0 });
    entry.clips++;
    if (row.correct) entry.correct++;
  }
  for (const entry of Object.values(categories)) entry.accuracy = ratio(entry.correct, entry.clips);
  const edits = rows.reduce((sum, row) => sum + row.edits, 0);
  const chars = rows.reduce((sum, row) => sum + row.referenceChars, 0);
  return {
    clips: rows.length,
    wakeRecall: ratio(shouldWake.filter((row) => row.wake).length, shouldWake.length),
    falseWakes,
    falseWakesPerHour: negativeHours ? Math.round((falseWakes / negativeHours) * 10) / 10 : null,
    intentAccuracy: ratio(rows.filter((row) => row.correct).length, rows.length),
    findAccuracy: ratio(finding.filter((row) => row.correct).length, finding.length),
    characterErrorRate: ratio(edits, chars),
    segmentationMismatches: rows.filter((row) => row.segments !== row.expectedSegments).length,
    latencyMs: { p50: percentile(latencies, 50), p95: percentile(latencies, 95) },
    categories,
  };
}
