/* Session history belongs to this page, never localStorage. Only successful, complete turns
   enter the context. Cancellation invalidates late replies even if fetch ignores AbortSignal. */
export function createChatSession({ request = (...args) => fetch(...args), timeout = 90000 } = {}) {
  let history = [],
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
  async function ask(text, phase, bookId) {
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
      const response = await request("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: pending.signal,
        body: JSON.stringify({ text, phase, bookId, history, configuration }),
      });
      const result = await response.json();
      if (current !== generation) return { cancelled: true };
      if (!response.ok) return { error: result.error || `对话服务返回 ${response.status}` };
      if (typeof result.reply !== "string" || !result.reply.trim())
        return { error: "模型没有返回回答，请重试。" };
      if (result.reset) history = [];
      configuration = result.configuration;
      history.push({ role: "user", content: text }, { role: "assistant", content: result.reply });
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
    getState: () => ({ busy: Boolean(controller), turns: history.length / 2 }),
  };
}

export function bubblePreview(text) {
  const glyphs = Array.from(text.replace(/\s+/g, " ").trim());
  return glyphs.length <= 100
    ? glyphs.join("")
    : glyphs.slice(0, 80).join("") + "…完整回答见对话面板。";
}
