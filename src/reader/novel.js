/** Real text pagination measured in the current viewport; progress uses a character offset. */
export function createNovelReader({
  notice,
  onShow = () => {},
  onHide = () => {},
  onLinger = () => {},
}) {
  const section = document.createElement("section");
  section.id = "novelReader";
  section.hidden = true;
  section.setAttribute("aria-label", "小说正文阅读");
  section.innerHTML = `<div class="novel-shell"><header class="novel-toolbar"><div><strong id="novelTitle"></strong><small id="novelAuthor"></small></div><div><button id="fontDown" aria-label="缩小字号">A−</button><button id="fontUp" aria-label="放大字号">A＋</button><button id="closeNovel">返回 3D 书本</button></div></header><div class="novel-layout"><aside><strong>章节目录</strong><select id="novelToc" size="14" aria-label="章节目录"></select><a id="novelSource" target="_blank" rel="noopener noreferrer">正文来源</a><small id="novelLicense"></small></aside><div class="novel-paper"><h2 id="novelChapter"></h2><article id="novelText" tabindex="0" aria-label="当前页正文"></article><footer><button id="previousPage">← 上一页</button><span id="novelProgress" aria-live="polite"></span><button id="nextPage">下一页 →</button></footer></div></div></div>`;
  document.body.append(section);
  const $ = (id) => section.querySelector("#" + id);
  let documentBook = null,
    chapter = 0,
    offset = 0,
    end = 0,
    generation = 0,
    openedCover = false;
  let saveTimer,
    saveQueue = Promise.resolve(),
    size = Number(localStorage.getItem("hexu-reader-font")) || 20;
  size = Math.max(16, Math.min(30, size));
  const previousOffsets = new Map();
  function persist(keepalive = false) {
    clearTimeout(saveTimer);
    if (!documentBook) return;
    const id = documentBook.id,
      position = { chapter, offset };
    saveQueue = saveQueue
      .catch(() => {})
      .then(() =>
        fetch("/library/progress/" + id, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(position),
          keepalive,
        }),
      )
      .then((response) => {
        if (!response.ok) throw new Error("save failed");
      })
      .catch(() => notice("阅读进度暂未保存，请检查本地书库服务"));
  }
  function fit(text, start) {
    const article = $("novelText");
    let low = 1,
      high = Math.min(text.length - start, 8000),
      best = 1;
    if (high <= 0) {
      article.textContent = "";
      return start;
    }
    while (low <= high) {
      const count = Math.floor((low + high) / 2);
      article.textContent = text.slice(start, start + count);
      if (article.scrollHeight <= article.clientHeight + 1) {
        best = count;
        low = count + 1;
      } else high = count - 1;
    }
    let finish = start + best;
    if (finish < text.length && /[\uD800-\uDBFF]/.test(text[finish - 1])) finish--;
    return Math.max(start + 1, finish);
  }
  function render() {
    if (!documentBook || section.hidden) return;
    $("novelToc").size = innerWidth <= 700 ? 1 : 14;
    const current = documentBook.chapters[chapter];
    offset = Math.max(0, Math.min(offset, Math.max(0, current.body.length - 1)));
    // Lay out the heading before measuring: a new chapter can occupy multiple lines.
    $("novelChapter").textContent = current.title;
    $("novelProgress").textContent = `${chapter + 1} / ${documentBook.chapters.length} 章 · 100%`;
    $("novelText").style.fontSize = size + "px";
    end = fit(current.body, offset);
    previousOffsets.set(chapter + ":" + end, offset);
    $("novelText").textContent = current.body.slice(offset, end);
    $("novelChapter").textContent = current.title;
    $("novelToc").value = String(chapter);
    $("previousPage").disabled = chapter === 0 && offset === 0;
    $("nextPage").disabled =
      chapter === documentBook.chapters.length - 1 && end >= current.body.length;
    $("novelProgress").textContent =
      `${chapter + 1} / ${documentBook.chapters.length} 章 · ${Math.round((end / current.body.length) * 100)}%`;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(persist, 350);
  }
  function show() {
    if (!documentBook) {
      notice("这本书还没有本地正文，请先在正文书库检索并下载");
      return;
    }
    section.hidden = false;
    document.body.classList.add("novel-reading");
    onShow(section.querySelector(".novel-shell"));
    render();
    $("novelText").focus({ preventScroll: true });
  }
  function hide() {
    if (!section.hidden) persist();
    section.hidden = true;
    document.body.classList.remove("novel-reading");
    onHide();
  }
  async function attach(book) {
    hide();
    documentBook = null;
    openedCover = false;
    offered = false;
    clearTimeout(lingerTimer);
    previousOffsets.clear();
    const current = ++generation;
    if (!book?.localBookId) return;
    try {
      const response = await fetch("/library/books/" + book.localBookId, { cache: "no-store" });
      if (!response.ok) throw new Error("正文读取失败");
      const data = await response.json();
      if (current !== generation) return;
      documentBook = data;
      chapter = Math.max(0, Math.min(data.progress.chapter, data.chapters.length - 1));
      offset = data.progress.offset;
      $("novelTitle").textContent = data.title;
      $("novelAuthor").textContent = data.author;
      $("novelLicense").textContent = data.license;
      $("novelSource").hidden = !data.source_url;
      if (/^https?:\/\//.test(data.source_url)) $("novelSource").href = data.source_url;
      $("novelToc").replaceChildren(
        ...data.chapters.map((entry, index) => {
          const option = document.createElement("option");
          option.value = index;
          option.textContent = entry.title;
          return option;
        }),
      );
      if (openedCover) show();
    } catch (error) {
      if (current === generation) notice(error.message);
    }
  }
  function next() {
    if (!documentBook) return;
    if (end < documentBook.chapters[chapter].body.length) offset = end;
    else if (chapter < documentBook.chapters.length - 1) {
      chapter++;
      offset = 0;
    }
    render();
  }
  function previous() {
    if (!documentBook) return;
    if (offset === 0 && chapter > 0) {
      chapter--;
      offset = documentBook.chapters[chapter].body.length;
    } else if (offset === 0) return;
    const cached = previousOffsets.get(chapter + ":" + offset);
    if (cached !== undefined) {
      offset = cached;
      render();
      return;
    }
    const text = documentBook.chapters[chapter].body;
    let start = 0,
      last = 0;
    // Rebuild boundaries for a resumed position or after a viewport/font change.
    while (start < offset) {
      last = start;
      const stop = fit(text, start);
      if (stop >= offset) break;
      start = stop;
    }
    offset = last;
    render();
  }
  $("nextPage").onclick = next;
  $("previousPage").onclick = stepBack;
  $("closeNovel").onclick = hide;
  $("novelToc").onchange = () => {
    chapter = Number($("novelToc").value);
    offset = 0;
    render();
  };
  function font(delta) {
    size = Math.max(16, Math.min(30, size + delta));
    localStorage.setItem("hexu-reader-font", size);
    previousOffsets.clear();
    render();
  }
  $("fontUp").onclick = () => font(2);
  $("fontDown").onclick = () => font(-2);
  let touchStart = null;
  $("novelText").onpointerdown = (event) => {
    touchStart = { x: event.clientX, y: event.clientY };
  };
  $("novelText").onpointerup = (event) => {
    if (
      touchStart &&
      Math.abs(event.clientY - touchStart.y) < 60 &&
      Math.abs(event.clientX - touchStart.x) > 65
    ) {
      if (event.clientX < touchStart.x) next();
      else stepBack();
    }
    touchStart = null;
  };
  window.addEventListener("resize", () => {
    previousOffsets.clear();
    render();
  });
  window.addEventListener("pagehide", () => persist(true));
  /* Going back a page and staying there is the reader puzzling over something. After
     LINGER_MS on that same page 小和 offers, once per opened book, to explain (onLinger). */
  const LINGER_MS = 30000;
  let lingerTimer = null;
  let offered = false;
  function stepBack() {
    previous();
    clearTimeout(lingerTimer);
    const here = chapter + ":" + offset;
    lingerTimer = setTimeout(() => {
      if (offered || section.hidden || chapter + ":" + offset !== here) return;
      offered = true;
      onLinger();
    }, LINGER_MS);
  }
  /** Open the text at chapter `index` (0-based), as 「翻到第五章」 asks, at character `at`
   *  within it (a bookmark's place) or its start. */
  function goTo(index, at = 0) {
    if (!documentBook || !Number.isInteger(index)) return false;
    chapter = Math.max(0, Math.min(index, documentBook.chapters.length - 1));
    offset = Number.isInteger(at) && at > 0 ? at : 0;
    show();
    return true;
  }
  /** 「字大一点」: one step larger or smaller, or back to the default size. */
  function fontSize(step) {
    if (step === "larger") font(2);
    else if (step === "smaller") font(-2);
    else if (step === "default") font(20 - size);
  }
  return {
    attach,
    show,
    hide,
    next,
    previous: stepBack,
    pageText: () => (section.hidden ? "" : $("novelText").textContent),
    goTo,
    fontSize,
    clear() {
      hide();
      generation++;
      documentBook = null;
      openedCover = false;
    },
    cover(value) {
      const wasOpen = openedCover;
      openedCover = value;
      if (value && !wasOpen && documentBook) show();
      if (!value) hide();
    },
    get visible() {
      return !section.hidden;
    },
    handleKey(event) {
      if (section.hidden) return false;
      if (event.key === "Escape") hide();
      else if (event.key === "ArrowRight" || event.key === "PageDown") next();
      else if (event.key === "ArrowLeft" || event.key === "PageUp") stepBack();
      else return false;
      event.preventDefault();
      return true;
    },
    getState: () => ({ bookId: documentBook?.id, chapter, offset, end, visible: !section.hidden }),
  };
}
