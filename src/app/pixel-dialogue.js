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
  root.innerHTML = `<div class="bubble-frame"><div class="bubble-heading" aria-hidden="true"><span class="bubble-led"></span><span>小和 / XIAO HE</span><span class="bubble-dots">···</span></div><div class="bubble-copy" aria-hidden="true"><span class="bubble-measure"></span><span class="bubble-writing"><span id="bubbleText"></span><i class="bubble-caret"></i></span></div><div class="bubble-controls"><span class="bubble-status" aria-live="off"></span><button type="button" data-bubble-finish>显示全文</button><button type="button" data-bubble-stop hidden>停止等待</button><button type="button" data-bubble-close>收起</button></div></div><span id="bubbleAnnouncement" class="visually-hidden" role="status" aria-live="polite" aria-atomic="true"></span>`;
  const text = root.querySelector("#bubbleText"),
    measure = root.querySelector(".bubble-measure");
  const copy = root.querySelector(".bubble-copy");
  const finishButton = root.querySelector("[data-bubble-finish]");
  const stopButton = root.querySelector("[data-bubble-stop]");
  const status = root.querySelector(".bubble-status");
  let following = true,
    interactive = false;
  copy.addEventListener(
    "wheel",
    () => {
      following = false;
    },
    { passive: true },
  );
  copy.addEventListener("scroll", () => {
    following = copy.scrollHeight - copy.scrollTop - copy.clientHeight < 24;
  });
  const announcement = root.querySelector("#bubbleAnnouncement");
  let message = "",
    visible = false,
    timer = null,
    hold = 0,
    typingSound = true;
  const writer = createTypewriter({
    onText: (value) => {
      text.textContent = value;
      if (following && visible) {
        const bottom = text.getBoundingClientRect().bottom - copy.getBoundingClientRect().bottom;
        if (bottom > 0) copy.scrollTop += bottom;
      }
    },
    onGlyph: (glyph, index) => {
      if (typingSound && !document.hidden && getComputedStyle(root).display !== "none")
        sounds.type(glyph, index);
    },
    onDone: () => {
      root.classList.remove("typing");
      finishButton.hidden = true;
      status.textContent = stopButton.hidden ? "可滚动阅读" : "正在回应";
      if (visible && hold) timer = setTimeout(hide, hold);
    },
  });
  finishButton.onclick = () => {
    following = false;
    writer.finish();
  };
  root.querySelector("[data-bubble-close]").onclick = hide;
  root.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (event.key === "Escape") {
      event.preventDefault();
      hide();
    }
  });
  function hide() {
    clearTimeout(timer);
    timer = null;
    writer.stop();
    sounds.stop();
    visible = false;
    root.classList.remove("show", "typing");
    if (root.contains(document.activeElement)) document.activeElement.blur();
    root.setAttribute("aria-hidden", "true");
  }
  function show(value, duration = 6500, options = {}) {
    clearTimeout(timer);
    writer.stop();
    sounds.stop();
    message = String(value);
    interactive = options.interactive === true;
    root.classList.toggle("interactive", interactive);
    stopButton.hidden = typeof options.onCancel !== "function";
    stopButton.onclick = options.onCancel || null;
    finishButton.hidden = !stopButton.hidden || options.instant === true;
    status.textContent = stopButton.hidden ? "逐字显示 · 可滚动" : "正在回应";
    copy.scrollTop = 0;
    following = true;
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
  return {
    show,
    hide,
    getState: () => ({
      message,
      visible,
      persistent: visible && interactive && !hold,
      ...writer.getState(),
    }),
  };
}
