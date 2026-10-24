/* Session history belongs to this page, never localStorage. Only successful, complete turns
   enter the context. Cancellation invalidates late replies even if fetch ignores AbortSignal.

   Replies stream from /chat/stream as one JSON event per line, so onText(replySoFar) can show
   and speak the answer while the model is still writing it. A server that answers with one
   plain JSON object instead is accepted too. */

/** Read newline-delimited JSON events from a fetch Response, one callback per event. */
async function readEvents(response, onEvent, stale) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (stale()) {
      reader.cancel().catch(() => {});
      return;
    }
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line));
    }
    if (done) break;
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}
export function createChatSession({ request = (...args) => fetch(...args), timeout = 90000 } = {}) {
  let history = [],
    total = 0, // completed turns ever, so a summary can take only what is new since the last one
    configuration = "",
    controller = null,
    generation = 0;
  function cancel() {
    generation++;
    controller?.abort();
    controller = null;
  }
  function clear() {
    cancel();
    history = [];
    configuration = "";
  }
  async function ask(text, phase, bookId, { onText, onAction } = {}) {
    if (controller) return { error: "小和正在回答，请等待或停止当前回答。", busy: true };
    const current = ++generation;
    const pending = new AbortController();
    controller = pending;
    const timer = setTimeout(() => pending.abort(), timeout);
    try {
      // Re-read settings every turn: saving another provider takes effect without a reload.
      const readyResponse = await request("/chat/ready", {
        cache: "no-store",
        signal: pending.signal,
      });
      const ready = await readyResponse.json();
      if (current !== generation) return { cancelled: true };
      if (!readyResponse.ok || !ready.ready)
        return { error: ready.reason || "请在本机设置配置大模型 API。" };
      if (ready.configuration !== configuration) {
        history = [];
        configuration = ready.configuration;
      }
      const response = await request("/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: pending.signal,
        body: JSON.stringify({ text, phase, bookId, history, configuration }),
      });
      let result;
      const streamed = /ndjson/.test(response.headers?.get?.("Content-Type") ?? "");
      if (response.ok && streamed && response.body) {
        let reply = "";
        await readEvents(
          response,
          (event) => {
            if (event.type === "delta" && typeof event.text === "string") {
              reply += event.text;
              onText?.(reply);
            } else if (event.type === "action") onAction?.(event);
            else if (event.type === "done" || event.type === "error") result = event;
          },
          () => current !== generation,
        );
        if (current !== generation) return { cancelled: true };
        if (!result) return { error: "回答中途断开，请重试。" };
        if (result.type === "error") return { error: result.error || "模型没有返回回答，请重试。" };
      } else {
        result = await response.json();
        if (current !== generation) return { cancelled: true };
        if (!response.ok) return { error: result.error || `对话服务返回 ${response.status}` };
      }
      if (typeof result.reply !== "string" || !result.reply.trim())
        return { error: "模型没有返回回答，请重试。" };
      if (result.reset) history = [];
      configuration = result.configuration;
      history.push({ role: "user", content: text }, { role: "assistant", content: result.reply });
      total++;
      // Drop whole pairs, never an orphan answer. Match server character and message budgets.
      while (
        history.length > 12 ||
        history.reduce((n, item) => n + Array.from(item.content).length, 0) > 24000
      )
        history.splice(0, 2);
      return result;
    } catch (error) {
      if (current !== generation) return { cancelled: true };
      return {
        error:
          error.name === "AbortError"
            ? "模型响应超时，请重试或更换模型。"
            : "无法连接对话服务，请检查本机服务与网络。",
      };
    } finally {
      clearTimeout(timer);
      if (current === generation) controller = null;
    }
  }
  return {
    ask,
    cancel,
    clear,
    /** The last `turns` completed turns still in context, as the server validates them. */
    recent: (turns) => history.slice(-2 * turns).map((entry) => ({ ...entry })),
    getState: () => ({ busy: Boolean(controller), turns: history.length / 2, total }),
  };
}
