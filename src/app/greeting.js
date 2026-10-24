/* One greeting when the library opens, made here from the clock and what 小和 remembers. It costs
   no model call, appears at most once per start, never interrupts (only in IDLE with no bubble or
   panel open), and can be switched off in the local settings. */
export const GREETING_PREFERENCE = "hexu-greeting"; // "off" disables it
const LAST_VISIT = "hexu-last-visit";
const DAY = 86400000;

function timeOfDay(hour) {
  if (hour < 5) return "夜深了";
  if (hour < 11) return "早上好";
  if (hour < 13) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

/** The greeting for this start, from the time, the last visit and the memory snapshot. */
export function composeGreeting({ now = new Date(), lastVisit = null, memory = {} } = {}) {
  const parts = [timeOfDay(now.getHours()) + "！"];
  if (lastVisit && now - lastVisit > 3 * DAY) parts.push("好久不见呀。");
  const book = (memory.enabled === false ? [] : (memory.reading ?? []))[0];
  if (book?.title) {
    parts.push(
      book.chapter_title
        ? `上次读到《${book.title}》第 ${book.chapter + 1} 章「${book.chapter_title}」，要接着读吗？`
        : `上次翻开的《${book.title}》，还想继续读吗？`,
    );
  } else parts.push(now.getHours() < 5 ? "看书别太晚哦，有想找的书就叫我。" : "有想找的书就叫我。");
  return parts.join("");
}

export function createGreeting({
  say,
  ready, // () => true when it would interrupt nothing
  storage = globalThis.localStorage,
  request = (...args) => fetch(...args),
  clock = () => new Date(),
  delay = 3500,
} = {}) {
  let done = false;
  const read = (key) => {
    try {
      return storage?.getItem(key) ?? null;
    } catch {
      return null;
    }
  };
  const lastVisit = Number(read(LAST_VISIT)) || null;
  const remember = () => {
    try {
      storage?.setItem(LAST_VISIT, String(+clock()));
    } catch {}
  };
  globalThis.addEventListener?.("pagehide", remember);
  async function greet() {
    if (done || read(GREETING_PREFERENCE) === "off") return null;
    let memory = {};
    try {
      const response = await request("/memory/state?peek=1", { cache: "no-store" });
      if (response.ok) memory = await response.json();
    } catch {}
    for (let i = 0; i < 20 && !ready(); i++) await new Promise((r) => setTimeout(r, 1500));
    if (done || !ready()) return null;
    done = true;
    const text = composeGreeting({
      now: clock(),
      lastVisit: lastVisit && new Date(lastVisit),
      memory,
    });
    say(text);
    remember();
    return text;
  }
  return {
    start: () => new Promise((resolve) => setTimeout(() => resolve(greet()), delay)),
    greet,
  };
}
