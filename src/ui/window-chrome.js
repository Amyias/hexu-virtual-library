/* The window's own buttons, and knowing whether to show them at all.

The window is frameless so that the page's bar can *be* the title bar (root title bars refract
nothing — there is nothing behind them). That moves minimising, maximising and closing out of the
operating system's hands and into this page's. The three buttons call back into the program through
pywebview's bridge; the Python side lives in tools/window_host.py.

Dragging is not here: it is a CSS class — `pywebview-drag-region` — that pywebview itself watches,
because a Python-side move is the only kind available once there is no caption to drag.

In an ordinary browser tab there is no window to control, `window.pywebview` does not exist, and
none of this runs: the page is the same page, minus the buttons.
*/

/* The bridge is injected before this module may run or after, depending on the load order, so
   both cases are handled: the event for the normal path, the direct check for the late one. */
function whenBridgeReady(callback) {
  if (window.pywebview && window.pywebview.api && Object.keys(window.pywebview.api).length) {
    callback();
    return;
  }
  window.addEventListener("pywebviewready", callback, { once: true });
}

/** Call one of the window actions exposed by the program, tolerating a bridge that is not there. */
async function call(action, ...args) {
  const api = window.pywebview && window.pywebview.api;
  if (!api || typeof api[action] !== "function") return null;
  try {
    return await api[action](...args);
  } catch (error) {
    console.warn("window action failed:", action, error);
    return null;
  }
}

export function createWindowChrome({ bar } = {}) {
  const buttons = [...document.querySelectorAll("[data-window-action]")];
  let maximized = false;

  async function syncMaximizedState() {
    const state = await call("maximized");
    const next = Boolean(state);
    if (next !== maximized) {
      maximized = next;
      document.body.classList.toggle("window-maximized", maximized);
    }
  }

  function bind() {
    document.body.classList.add("in-app-window");

    for (const button of buttons) {
      button.addEventListener("click", async (event) => {
        event.preventDefault();
        const action = button.dataset.windowAction;
        await call(action === "toggle-maximize" ? "toggle_maximize" : action);
        if (action === "toggle-maximize") syncMaximizedState();
      });
    }

    // Dragging the bar is implemented here rather than with pywebview's `pywebview-drag-region`.
    // That one computes movement as `screenX - clientX` — screen coordinates minus
    // window-relative ones — so the window teleports to the pointer instead of following it.
    // Doing it from the window's own origin is a few lines and behaves the way a title bar should.
    let drag = null;
    let queued = 0;

    bar?.addEventListener("mousedown", async (event) => {
      if (event.button !== 0) return;
      if (event.target.closest("[data-window-action]")) return;
      // Maximized windows are not draggable through their title bar either; the system restores
      // them when the bar is dragged, which the maximize button covers.
      if (document.body.classList.contains("window-maximized")) return;
      drag = { fromX: event.screenX, fromY: event.screenY, origin: null };
      const origin = await call("bounds");
      if (drag) drag.origin = origin;
      event.preventDefault();
    });

    window.addEventListener("mousemove", (event) => {
      if (!drag || !drag.origin) return;
      const x = drag.origin.x + (event.screenX - drag.fromX);
      const y = drag.origin.y + (event.screenY - drag.fromY);
      // One call per frame: every move is a round trip to the program, and a mouse can generate
      // far more of them than a window needs to be repositioned.
      cancelAnimationFrame(queued);
      queued = requestAnimationFrame(() => call("move", x, y));
    });
    window.addEventListener("mouseup", () => {
      drag = null;
    });

    // Double-clicking a title bar maximizes it — the same gesture the system provides, which is
    // one of the habits this page has to keep once it draws the title bar itself.
    bar?.addEventListener("dblclick", async (event) => {
      if (event.target.closest("[data-window-action]")) return;
      await call("toggle_maximize");
      syncMaximizedState();
    });

    // The window can also be maximized by Win+Up or by dragging it to the top edge, neither of
    // which goes through the button; resizing is when that becomes visible here.
    window.addEventListener("resize", syncMaximizedState);
    syncMaximizedState();
  }

  whenBridgeReady(bind);

  return {
    get inWindow() {
      return document.body.classList.contains("in-app-window");
    },
    get maximized() {
      return maximized;
    },
  };
}
