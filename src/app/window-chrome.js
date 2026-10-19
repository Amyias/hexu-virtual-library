const controls = {
  minimize: '<path d="M4 8h8"/>',
  maximize: '<rect x="4" y="4" width="8" height="8" rx="1"/>',
  close: '<path d="m4 4 8 8m0-8-8 8"/>',
};

export function installDesktopChrome(host = window) {
  let bar;
  async function connect() {
    if (bar || !host.pywebview?.api?.desktop_state) return;
    const api = host.pywebview.api;
    const state = await api.desktop_state().catch(() => null);
    if (!state || bar || host.document.querySelector(".desktop-titlebar")) return;
    const doc = host.document;
    const css = doc.createElement("link");
    css.rel = "stylesheet";
    css.href = new URL("../styles/window-chrome.css", import.meta.url).href;
    doc.head.append(css);
    bar = doc.createElement("div");
    bar.className = "desktop-titlebar";
    bar.setAttribute("aria-label", "窗口标题栏");
    bar.innerHTML = `<svg class="window-glass-filter" aria-hidden="true"><defs><filter id="hexuGlassWarp" x="-10%" y="-50%" width="120%" height="200%" color-interpolation-filters="sRGB"><feTurbulence type="fractalNoise" baseFrequency=".012 .055" numOctaves="2" seed="4" result="ripple"/><feDisplacementMap in="SourceGraphic" in2="ripple" scale="12" xChannelSelector="R" yChannelSelector="G"/></filter></defs></svg>
      <div class="window-drag"><img src="${new URL("../../public/favicon.ico", import.meta.url).href}" alt="" draggable="false"><span>和序图书馆</span></div>
      <div class="window-controls" aria-label="窗口操作">${Object.entries(controls)
        .map(
          ([action, path]) =>
            `<button type="button" data-window-action="${action}" aria-label="${{ minimize: "最小化", maximize: "最大化", close: "关闭窗口" }[action]}"><svg viewBox="0 0 16 16" aria-hidden="true">${path}</svg></button>`,
        )
        .join("")}</div>`;
    if (!state.nativeDrag) {
      const drag = bar.querySelector(".window-drag");
      drag.classList.add("pywebview-drag-region");
      drag.addEventListener("dblclick", () => action("maximize"));
    }
    const maximize = bar.querySelector('[data-window-action="maximize"]');
    function update(next) {
      if (!next) return;
      doc.documentElement.classList.toggle("window-maximized", next.maximized);
      maximize.setAttribute("aria-label", next.maximized ? "还原窗口" : "最大化");
      maximize.title = maximize.getAttribute("aria-label");
    }
    let busy = false;
    async function action(command) {
      if (busy) return;
      busy = true;
      try {
        update(await api.desktop_action(command));
      } catch {
        /* Closing destroys the document before its promise can resolve. */
      } finally {
        busy = false;
      }
    }
    for (const button of bar.querySelectorAll("button")) {
      button.title = button.getAttribute("aria-label");
      button.addEventListener("click", () => action(button.dataset.windowAction));
    }
    // Native double-clicks, Win+Up and restoring from the taskbar also update the control.
    let timer;
    const sync = () => {
      host.clearTimeout(timer);
      timer = host.setTimeout(
        () =>
          api
            .desktop_state()
            .then(update)
            .catch(() => {}),
        120,
      );
    };
    host.addEventListener("resize", sync);
    host.addEventListener("focus", sync);
    if (!host.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      bar.addEventListener("pointermove", (event) => {
        bar.style.setProperty("--glass-light", `${Math.round(event.clientX)}px`);
      });
    }
    for (const edge of ["n", "s", "e", "w", "ne", "nw", "se", "sw"]) {
      const grip = doc.createElement("div");
      grip.className = `window-resize-edge edge-${edge}`;
      grip.setAttribute("aria-hidden", "true");
      grip.addEventListener("pointerdown", async (event) => {
        if (event.button !== 0 || doc.documentElement.classList.contains("window-maximized"))
          return;
        event.preventDefault();
        event.stopPropagation();
        grip.setPointerCapture(event.pointerId);
        const start = { x: event.screenX, y: event.screenY };
        let latest,
          moving = false,
          stopped = false;
        const flush = async () => {
          if (moving || !latest) return;
          moving = true;
          while (latest) {
            const delta = latest;
            latest = null;
            await api.resize_move(delta.x, delta.y).catch(() => {});
          }
          moving = false;
          if (stopped) await api.resize_end().catch(() => {});
        };
        const move = (next) => {
          latest = { x: next.screenX - start.x, y: next.screenY - start.y };
          void flush();
        };
        const end = (next) => {
          stopped = true;
          grip.removeEventListener("pointermove", move);
          grip.removeEventListener("pointerup", end);
          grip.removeEventListener("pointercancel", end);
          if (grip.hasPointerCapture(next.pointerId)) grip.releasePointerCapture(next.pointerId);
          move(next);
        };
        if (!(await api.resize_start(edge).catch(() => false))) {
          if (grip.hasPointerCapture(event.pointerId)) grip.releasePointerCapture(event.pointerId);
          return;
        }
        // The pointer may already have been released while the native bridge started.
        if (!grip.hasPointerCapture(event.pointerId)) {
          await api.resize_end();
          return;
        }
        grip.addEventListener("pointermove", move);
        grip.addEventListener("pointerup", end);
        grip.addEventListener("pointercancel", end);
      });
      doc.body.append(grip);
    }
    doc.body.prepend(bar);
    doc.documentElement.classList.add("desktop-shell");
    update(state);
  }
  host.addEventListener(
    "pywebviewready",
    () => {
      void connect();
    },
    { once: true },
  );
  void connect();
}
