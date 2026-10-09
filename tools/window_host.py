"""Show the library in a real window instead of handing the page to a browser.

pywebview draws a native window around the page, using the WebView2 runtime that ships with
Windows, so the program opens the way any other program does — one window, no tabs, no console.
The web server keeps serving the page exactly as before; the window is only how it is displayed.

The microphone is the reason this module is not three lines long. WebView2 **denies** camera and
microphone requests unless the host application answers the permission request itself, and it
shows no prompt of its own — a page that asks for the microphone simply gets a rejection.
pywebview 6.2.1 does not subscribe to that event (grep its two Windows backends: the only
permission handling in the whole package is in the Qt backend). So the grant is installed here,
into the window that owns the request, before the page can ask.

Speech is the whole point of this library, so the window is only offered when that grant went in:
`available()` returns False if anything about the native stack is missing, and the caller falls
back to the browser rather than opening a window in which nobody can talk.

Only the packaged local build uses this. The server deployment never opens a window.
"""
import sys
import time

#: Seconds to wait for the page to report on the microphone in the diagnostic probe.
PROBE_TIMEOUT = 12.0


def available():
    """Whether a window can be offered at all, and why not when it cannot."""
    if not sys.platform.startswith("win"):
        return False, f"当前系统是 {sys.platform}，内嵌窗口只在 Windows 上提供"
    try:
        import clr  # noqa: F401
        import webview  # noqa: F401
    except Exception as error:
        return False, f"缺少内嵌窗口需要的组件（{type(error).__name__}: {error}）"
    return True, ""


def install_window_hooks(icon=None):
    """Wire the window up the way this program wants it, from inside pywebview's init callback.

    Two things happen here, and both have to happen at this exact moment:

    - **The microphone is granted.** WebView2 denies camera and microphone requests unless the
      host application answers the permission request itself, and it shows no prompt of its own —
      a page that asks for the microphone simply gets a rejection. This hook answers yes for the
      microphone, and only the microphone, for this window's page. `Handled` stops the request
      from travelling any further, so nothing can override the answer later.
    - **The window gets its icon.** The WinForms form is pywebview's own window object and is only
      reachable from the backend that creates it, which is why this is done here rather than by
      passing a parameter to `webview.start`.

    Hooked onto pywebview's init callback rather than onto the window object, because that
    callback is where `CoreWebView2` first exists — neither subscription can be made any earlier.

    Returns True when the hook is in place.
    """
    try:
        from webview.platforms import edgechromium

        # Importing the backend above registers the WebView2 interop assemblies, which is what
        # makes these names resolvable.
        from Microsoft.Web.WebView2.Core import (
            CoreWebView2PermissionKind,
            CoreWebView2PermissionState,
        )
    except Exception:
        return False

    def on_permission_requested(sender, args):
        if args.PermissionKind == CoreWebView2PermissionKind.Microphone:
            args.State = CoreWebView2PermissionState.Allow
            args.Handled = True

    original = edgechromium.EdgeChrome.on_webview_ready

    def on_webview_ready(self, sender, args):
        original(self, sender, args)
        try:
            sender.CoreWebView2.PermissionRequested += on_permission_requested
        except Exception:
            # A window without the grant is still better than no window; the page reports the
            # microphone as unavailable and the reader can be told to use the browser instead.
            pass
        if icon:
            try:
                from System.Drawing import Icon

                self.form.Icon = Icon(str(icon))
            except Exception:
                pass  # the executable's own icon still shows in the taskbar
        # Frameless took the resize border away with the caption; this gives it back, from a
        # worker thread and retried, because the style pywebview applies while showing the window
        # would otherwise overwrite an earlier attempt.
        restore_resize_frame(self.form)

    edgechromium.EdgeChrome.on_webview_ready = on_webview_ready
    return True


def restore_resize_frame(form, attempts=40, interval=0.1):
    """Give the window back its resize border, which frameless takes away with the caption.

    `FormBorderStyle.None` drops WS_CAPTION and WS_THICKFRAME together, and Windows then answers
    "client area" for every point of the window: measured, all four edges returned HTCLIENT, so
    the window could not be resized at all — a window you cannot resize is not a normal program.

    Putting WS_THICKFRAME back is enough. Measured again afterwards: HTBOTTOMRIGHT, HTRIGHT,
    HTBOTTOM and HTTOP at the edges, HTCLIENT in the middle. Resizing works, and no caption comes
    back with it.

    Retried until it sticks, and always from a worker thread. A single attempt from the WebView2
    init callback looked successful and changed nothing: pywebview applies the frameless style
    while it is still showing the window, so an attempt made too early is quietly undone. Sleeping
    in the callback would freeze the window for the length of this loop, which is why it is here.

    The other obvious route was tried first and does not work here: leaving the border style
    alone and calling DwmExtendFrameIntoClientArea with a caption-height top margin. The call
    reports success (hresult 0) and changes nothing — captures with margins 0, 64 and 200 are
    pixel-identical, caption included. Recorded so nobody spends that afternoon again.
    """
    import ctypes
    import threading
    import time

    GWL_STYLE = -16
    WS_THICKFRAME = 0x00040000
    SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_FRAMECHANGED = 0x0002, 0x0001, 0x0004, 0x0020

    def settle():
        try:
            # .NET hands back an IntPtr, which int() refuses; ToInt64() is the way through.
            handle = int(form.Handle.ToInt64())
            if not handle:
                print("[frame] window handle not available yet", flush=True)
                return False
            for _ in range(attempts):
                style = ctypes.windll.user32.GetWindowLongW(handle, GWL_STYLE)
                if style & WS_THICKFRAME:
                    return True
                ctypes.windll.user32.SetWindowLongW(handle, GWL_STYLE, style | WS_THICKFRAME)
                ctypes.windll.user32.SetWindowPos(
                    handle, 0, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
                )
                time.sleep(interval)
            print("[frame] resize border could not be restored", flush=True)
        except Exception as error:
            print(f"[frame] failed: {type(error).__name__}: {error}", flush=True)
            return False
        return False

    threading.Thread(target=settle, daemon=True).start()
    return True


class WindowControls:
    """The window's own buttons and edges, for a page that has to provide them.

    A frameless window has no title bar, so the page draws one — and that makes moving, resizing,
    minimising, maximising and closing this program's business instead of the operating system's.
    Each call goes through pywebview's Window API, which posts to the GUI thread whichever thread
    asked.

    Whether the window is maximized is followed through pywebview's own events rather than with a
    flag of our own: the reader can also double-click the title bar or press Win+Up, and the
    button has to agree with the window afterwards either way.
    """

    def __init__(self):
        self._window = None
        self._maximized = False

    def attach(self, window):
        """Subscribe to the window's state changes. Returns self, so it reads as one chain."""
        self._window = window
        for name, maximized in (("maximized", True), ("restored", False), ("minimized", False)):
            def track(*_args, _maximized=maximized):
                self._maximized = _maximized

            setattr(window.events, name, getattr(window.events, name) + track)
        return self

    # --- the calls the page makes ------------------------------------------
    def minimize(self):
        if self._window:
            self._window.minimize()
        return True

    def toggle_maximize(self):
        if not self._window:
            return False
        self._window.restore() if self._maximized else self._window.maximize()
        return True

    def close(self):
        if self._window:
            self._window.destroy()
        return True

    def resize(self, width, height, corner="nw"):
        """Resize as an edge is dragged. `corner` names the corner that must stay put, which is
        what makes dragging the left or top edge behave like dragging the left or top edge."""
        if not self._window:
            return False
        from webview.window import FixPoint

        fixed = {
            "nw": FixPoint.NORTH | FixPoint.WEST,
            "ne": FixPoint.NORTH | FixPoint.EAST,
            "sw": FixPoint.SOUTH | FixPoint.WEST,
            "se": FixPoint.SOUTH | FixPoint.EAST,
        }.get(str(corner), FixPoint.NORTH | FixPoint.WEST)
        self._window.resize(max(200, int(width)), max(100, int(height)), fixed)
        return True

    def move(self, x, y):
        if self._window:
            self._window.move(int(x), int(y))
        return True

    def bounds(self):
        """The window's position and size, so the page can drag it by the title bar.

        pywebview's own drag region cannot be used for that: it computes the movement as
        `screenX - clientX`, mixing screen coordinates with window-relative ones, so the window
        teleports to the pointer on the first movement instead of following it. Dragging a title
        bar needs the window's own origin, which is what this returns.
        """
        if not self._window:
            return None
        return {"x": self._window.x, "y": self._window.y,
                "width": self._window.width, "height": self._window.height}

    def maximized(self):
        return self._maximized


def run(url, title="和序图书馆", width=1280, height=820, icon=None, controls=None,
        debug_port=None):
    """Show the page in a window and block until it is closed. Returns True if it opened.

    Called on the main thread: the WinForms message loop has to own it.

    The window is frameless, so the page's own bar becomes the window's bar — and there is library
    behind it for glass to refract, where a native title bar had nothing behind it at all. The
    resize border is put back by restore_resize_frame, so the window still resizes from every edge.

    `easy_drag` is off on purpose: left on, pywebview turns *any* press on the page into a window
    drag, which would take the camera orbit and the cover drag with it. Dragging is the title
    bar's job, and the bar says so with pywebview's own `pywebview-drag-region` class.
    """
    if not install_window_hooks(icon):
        return False
    import webview

    if debug_port:
        # Off unless asked for: this is what lets a test drive the real window (buttons, dragging,
        # frame rate) instead of the reader having to click things and report back.
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(debug_port)

    created = webview.create_window(
        title, url, width=width, height=height, min_size=(880, 620),
        frameless=True, easy_drag=False, js_api=controls,
        # Paints the few pixels of resize border, which belong to the frame rather than the page.
        # Matching the page's own tone keeps that strip from reading as a white rim.
        background_color="#eaece5",
    )
    if controls is not None and created is not None:
        controls.attach(created)
    try:
        # Forcing the backend keeps it off the legacy mshtml renderer, which cannot run the page
        # at all. A missing WebView2 runtime raises here and the caller falls back to a browser.
        webview.start(gui="edgechromium")
    except Exception:
        return False
    return True


def close_windows():
    """Close every window this process opened.

    Needed because the update helper cannot rebuild a program that is still running: the request
    arrives on a server thread, and closing the window is what makes the window loop return so
    the program can exit."""
    try:
        import webview

        for window in list(getattr(webview, "windows", [])):
            try:
                window.destroy()
            except Exception:
                pass
    except Exception:
        pass


#: Runs inside the window and leaves its verdict on `window.__micProbe`, so the caller can read
#: it back with evaluate_js — an unresolved promise cannot be returned through that boundary.
#:
#: The audio context is reported alongside the microphone on purpose. Hands-free listening means
#: starting audio capture with no user gesture at all, and Chromium's autoplay policy leaves a
#: context created without one suspended — which would show up as a page that claims to be
#: listening and never hears anything.
MIC_PROBE_JS = """
(async () => {
  const report = { state: "asking" };
  try {
    const context = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    report.audioState = context.state;
    report.audioRate = context.sampleRate;
    await context.close();
  } catch (error) {
    report.audioState = "unavailable: " + error.name;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const track = stream.getAudioTracks()[0];
    const settings = track ? track.getSettings() : {};
    report.state = "granted";
    report.label = track ? track.label : "";
    report.sampleRate = settings.sampleRate || null;
    report.channelCount = settings.channelCount || null;
    // The track is stopped immediately and no audio is ever read: this answers "may we listen",
    // it does not listen.
    stream.getTracks().forEach((t) => t.stop());
  } catch (error) {
    report.state = "denied";
    report.error = error.name + ": " + error.message;
  }
  window.__micProbe = report;
  return "done";
})()
"""


def microphone_report(url, icon=None):
    """Open the window, ask the page whether it may use the microphone, and report.

    The answer comes from the page itself rather than from the permission handler, so it also
    proves the parts that matter together: the window came up, the page loaded over a secure
    origin (loopback counts as one), and a microphone track was actually handed over.
    """
    ready, reason = available()
    if not ready:
        return False, reason
    if not install_window_hooks(icon):
        return False, "无法为窗口安装麦克风授权（WebView2 互操作组件不可用）"
    import webview

    verdict = {"state": "timeout"}

    def probe(window):
        # The window is passed in explicitly: `webview.start(func)` calls `func()` with no
        # arguments (see webview/__init__.py, `threading.Thread(target=func, args=args)`), so a
        # function that expects one would raise inside the thread and leave the window open.
        try:
            time.sleep(1.5)  # let the page settle before asking
            window.evaluate_js(MIC_PROBE_JS)
            deadline = time.time() + PROBE_TIMEOUT
            while time.time() < deadline:
                current = window.evaluate_js("window.__micProbe")
                if isinstance(current, dict) and current.get("state") != "asking":
                    verdict.update(current)
                    break
                time.sleep(0.4)
        except Exception as error:
            verdict["state"] = "error"
            verdict["error"] = f"{type(error).__name__}: {error}"
        finally:
            # Unconditional: a window left open here would hang the whole program.
            try:
                window.destroy()
            except Exception:
                pass

    window = webview.create_window("麦克风检测 · 和序图书馆", url, width=760, height=520)
    try:
        webview.start(probe, args=(window,), gui="edgechromium")
    except Exception as error:
        return False, f"无法打开窗口：{type(error).__name__}: {error}"
    if verdict.get("state") == "granted":
        audio = verdict.get("audioState")
        note = "" if audio == "running" else f"，但音频上下文是 {audio}（免点击收听可能要在页面里点一下）"
        return True, (
            f"内嵌窗口可以使用麦克风（{verdict.get('sampleRate')} Hz，{verdict.get('label')}）"
            f"，音频上下文 {audio}{note}"
        )
    if verdict.get("state") == "denied":
        return False, f"窗口起来了，但页面拿不到麦克风：{verdict.get('error')}"
    if verdict.get("state") == "error":
        return False, f"窗口起来了，但探测出错：{verdict.get('error')}"
    return False, f"窗口起来了，但麦克风探测没有结果（{verdict.get('state')}）"


if __name__ == "__main__":
    ok, message = microphone_report(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090/")
    print(("就绪：" if ok else "不可用：") + message, flush=True)
    sys.exit(0 if ok else 1)
