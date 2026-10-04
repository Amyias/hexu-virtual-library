/* Semantic intent parsing, for phrasing the local rules cannot cover.

The rules in intent.js match titles and aliases literally, which is fast and free but cannot
read "霍金写的那本" or "讲宇宙起源最著名的那本书". When the deployment has a model configured
(tools/asr-server.py reads it from the environment), those go to the model instead — and only
those: anything the rules already place is answered locally and never costs a round trip.

Nothing here reaches the adapter in speech.js. That module has to dispatch synchronously inside
its result handler, which a network call cannot do, so this is consulted from the dispatcher in
app.js instead. Without a configured model every call here degrades to "no answer". */

const READY_PATH = "/understand/ready";
const UNDERSTAND_PATH = "/understand";
const TIMEOUT_MS = 12000;

/** Resolve to the semantic layer's readiness payload, or null when none is configured. */
export async function probeUnderstand() {
  try {
    const response = await fetch(READY_PATH, { cache: "no-store" });
    if (!response.ok) return null;
    const info = await response.json();
    return info && info.ready ? info : null;
  } catch {
    /* Static deployment, or no model configured: not an error, just no semantic layer. */
    return null;
  }
}

/** Ask the model to place one utterance. Never throws; an unreadable answer becomes "none". */
export async function understand(text, phase) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(UNDERSTAND_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, phase }),
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      return { action: "none", error: payload.error || `语义服务返回 ${response.status}` };
    }
    return payload;
  } catch (error) {
    return {
      action: "none",
      error: error.name === "AbortError" ? "语义服务响应超时" : "无法连接语义服务",
    };
  } finally {
    clearTimeout(timer);
  }
}
