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
/* The context budget, as the server checks it: six turns or 24,000 characters. Past it the oldest
   turns are not simply forgotten: they are folded into a short running summary (POST
   /chat/compact) that travels with later questions, and only KEEP_TURNS stay word for word.
   Folding several turns at once keeps it to one extra model call every few turns. */
const MAX_MESSAGES = 12;
const MAX_CHARS = 24000;
const KEEP_TURNS = 3;
const characters = (entries) => entries.reduce((n, item) => n + Array.from(item.content).length, 0);

export function createChatSession({ request = (...args) => fetch(...args), timeout = 90000 } = {}) {
  let history = [],
    total = 0, // completed turns ever, so a summary can take only what is new since the last one
    configuration = "",
    controller = null,
    generation = 0,
    digest = "", // the earlier turns of this conversation, compacted
    epoch = 0, // bumped when the conversation starts over, so a late digest is not kept
    compacting = null;
  function cancel() {
    generation++;
    controller?.abort();
    controller = null;
  }
  function clear() {
    cancel();
    history = [];
    configuration = "";
    digest = "";
    epoch++;
  }
  /** Fold `dropped` (whole turns) into the digest, in the background. A failure only loses
   *  those turns, as it did before compaction existed. */
  function compact(dropped) {
    const asked = epoch;
    compacting = request("/chat/compact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ digest, history: dropped }),
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (asked === epoch && typeof payload?.digest === "string" && payload.digest.trim())
          digest = payload.digest;
      })
      .catch(() => {})
      .finally(() => (compacting = null));
  }
  async function ask(text, phase, bookId, { onText, onAction, page } = {}) {
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
        digest = "";
        epoch++;
        configuration = ready.configuration;
      }
      const response = await request("/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: pending.signal,
        body: JSON.stringify({
          text,
          phase,
          bookId,
          history,
          configuration,
          ...(page ? { page } : {}),
          ...(digest ? { digest } : {}),
        }),
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
      if (result.reset) {
        history = [];
        digest = "";
        epoch++;
      }
      configuration = result.configuration;
      history.push({ role: "user", content: text }, { role: "assistant", content: result.reply });
      total++;
      if (history.length > MAX_MESSAGES || characters(history) > MAX_CHARS) {
        // Whole pairs only, never an orphan answer: keep the newest turns, fold the rest.
        const kept = history.slice(-2 * KEEP_TURNS);
        while (kept.length > 2 && characters(kept) > MAX_CHARS) kept.splice(0, 2);
        const dropped = history.slice(0, history.length - kept.length);
        history = kept;
        compact(dropped);
      }
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
    getState: () => ({
      busy: Boolean(controller),
      turns: history.length / 2,
      total,
      digest,
      compacting: Boolean(compacting),
    }),
  };
}
