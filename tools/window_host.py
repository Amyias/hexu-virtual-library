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

    edgechromium.EdgeChrome.on_webview_ready = on_webview_ready
    return True


def run(url, title="和序图书馆", width=1280, height=820, icon=None):
    """Show the page in a window and block until it is closed. Returns True if it opened.

    Called on the main thread: the WinForms message loop has to own it.
    """
    if not install_window_hooks(icon):
        return False
    import webview

    webview.create_window(title, url, width=width, height=height, min_size=(880, 620))
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
