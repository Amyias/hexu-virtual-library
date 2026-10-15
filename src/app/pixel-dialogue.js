const PUNCTUATION = /[，。！？、,.!?:：;；]/u;
export function splitGlyphs(text) {
  return typeof Intl.Segmenter === "function"
    ? [...new Intl.Segmenter("zh", { granularity: "grapheme" }).segment(text)].map(
        (item) => item.segment,
      )
    : Array.from(text);
}

/** One cancellable text stream. Replacing/hiding a reply cannot leave old letters or sounds. */
export function createTypewriter({
  onText,
  onGlyph = () => {},
  onDone = () => {},
  schedule = setTimeout,
  cancel = clearTimeout,
}) {
  let timer = null,
    generation = 0,
    glyphs = [],
    index = 0,
    typing = false;
  function stop() {
    generation++;
    cancel(timer);
    timer = null;
    typing = false;
  }
  function finish() {
    stop();
    index = glyphs.length;
    onText(glyphs.join(""));
    onDone();
  }
  function start(text, { instant = false } = {}) {
    stop();
    glyphs = splitGlyphs(text);
    index = 0;
    onText("");
    if (instant || !glyphs.length) {
      finish();
      return;
    }
    typing = true;
    const current = generation;
    function next() {
      if (current !== generation) return;
      const glyph = glyphs[index++];
      onText(glyphs.slice(0, index).join(""));
      onGlyph(glyph, index);
      if (index === glyphs.length) {
        timer = null;
        typing = false;
        onDone();
        return;
      }
      timer = schedule(next, PUNCTUATION.test(glyph) ? 170 : /[a-z0-9]/i.test(glyph) ? 42 : 65);
    }
    timer = schedule(next, 45);
  }
  return {
    start,
    stop,
    finish,
    getState: () => ({ typing, revealed: index, total: glyphs.length }),
  };
}

export function createPixelDialogue(root, sounds) {
  root.innerHTML = `<div class="bubble-frame" aria-hidden="true"><div class="bubble-heading"><span class="bubble-led"></span><span>小和 / XIAO HE</span><span class="bubble-dots">···</span></div><div class="bubble-copy"><span class="bubble-measure"></span><span class="bubble-writing"><span id="bubbleText"></span><i class="bubble-caret"></i></span></div></div><span id="bubbleAnnouncement" class="visually-hidden" role="status" aria-live="polite" aria-atomic="true"></span>`;
  const text = root.querySelector("#bubbleText"),
    measure = root.querySelector(".bubble-measure");
  const announcement = root.querySelector("#bubbleAnnouncement");
  let message = "",
    visible = false,
    timer = null,
    hold = 0,
    typingSound = true;
  const writer = createTypewriter({
    onText: (value) => {
      text.textContent = value;
    },
    onGlyph: (glyph, index) => {
      if (typingSound && !document.hidden && getComputedStyle(root).display !== "none")
        sounds.type(glyph, index);
    },
    onDone: () => {
      root.classList.remove("typing");
      if (visible && hold) timer = setTimeout(hide, hold);
    },
  });
  function hide() {
    clearTimeout(timer);
    timer = null;
    writer.stop();
    sounds.stop();
    visible = false;
    root.classList.remove("show", "typing");
    root.setAttribute("aria-hidden", "true");
  }
  function show(value, duration = 6500, options = {}) {
    clearTimeout(timer);
    writer.stop();
    sounds.stop();
    message = String(value);
    hold = duration;
    typingSound = options.typingSound !== false;
    measure.textContent = message + " ▂";
    // Announce the full reply once; animated text is excluded from the accessibility tree.
    root.setAttribute("aria-hidden", "false");
    visible = true;
    announcement.textContent = message;
    root.classList.add("show", "typing");
    if (!document.hidden && getComputedStyle(root).display !== "none") sounds.pop();
    // Reduced motion disables spatial pop/caret animation in CSS; text still types as requested.
    writer.start(message, { instant: options.instant === true });
  }
  return { show, hide, getState: () => ({ message, visible, ...writer.getState() }) };
}
