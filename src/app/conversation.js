/* Optional history opened explicitly by the reader. Every reply also appears fully in the bubble.
   Replies are always textContent: model output cannot inject scripts/HTML into the library. */
export function createConversation({ onSubmit, onCancel, onClear }) {
  const button = document.createElement("button");
  button.id = "chatButton";
  button.className = "chat-launch";
  button.textContent = "和 · 对话";
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-controls", "conversation");
  const panel = document.createElement("section");
  panel.id = "conversation";
  panel.className = "conversation";
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-labelledby", "conversationTitle");
  panel.innerHTML = `<div class="conversation-head"><strong id="conversationTitle">小和 / 对话</strong><button type="button" data-close aria-label="关闭对话面板">×</button></div>
    <p class="conversation-note">可以问问题、接着追问，也可以说“帮我找《书名》”。上下文仅在本次页面会话保留，最多最近 6 轮。</p>
    <div class="conversation-log" role="log" aria-label="对话记录" aria-live="polite"></div>
    <p class="conversation-state" role="status">配置大模型后即可开始自由对话。</p>
    <form><textarea aria-label="向小和提问" placeholder="想问些什么？" rows="2" maxlength="4000" required></textarea><button type="submit">发送 ↗</button></form>
    <div class="conversation-tools"><button type="button" data-stop disabled>停止等待</button><button type="button" data-clear>新对话</button><a href="/settings">模型设置</a></div>`;
  document.body.append(button, panel);
  const log = panel.querySelector(".conversation-log");
  const state = panel.querySelector(".conversation-state");
  const input = panel.querySelector("textarea");
  const send = panel.querySelector('[type="submit"]');
  const stop = panel.querySelector("[data-stop]");
  let pending = false,
    messages = 0;
  function show(focus = false) {
    panel.hidden = false;
    button.setAttribute("aria-expanded", "true");
    if (focus) input.focus();
  }
  function hide() {
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
    button.focus();
  }
  function status(text) {
    state.textContent = text;
  }
  function busy(value) {
    pending = value;
    send.disabled = value;
    input.disabled = value;
    stop.disabled = !value;
  }
  function append(role, text) {
    const item = document.createElement("article");
    item.className = "conversation-message " + role;
    const label = document.createElement("b");
    label.textContent = role === "user" ? "你" : role === "error" ? "连接提示" : "小和";
    const body = document.createElement("div");
    body.textContent = text;
    item.append(label, body);
    log.append(item);
    // Bound the visible transcript separately from the six-turn model context.
    while (log.children.length > 40) log.firstElementChild.remove();
    messages = log.children.length;
    log.scrollTop = log.scrollHeight;
  }
  button.onclick = () => (panel.hidden ? show(true) : hide());
  panel.querySelector("[data-close]").onclick = hide;
  panel.querySelector("form").onsubmit = (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || pending) return;
    input.value = "";
    onSubmit(text);
  };
  input.onkeydown = (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      panel.querySelector("form").requestSubmit();
    }
  };
  stop.onclick = () => {
    onCancel();
    busy(false);
    status("已停止等待。已发出的 API 请求可能仍会计费。");
  };
  panel.querySelector("[data-clear]").onclick = () => {
    onClear();
    busy(false);
    log.replaceChildren();
    messages = 0;
    status("已开启新对话，之前的上下文已清空。");
    input.focus();
  };
  panel.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (event.key === "Escape") {
      event.preventDefault();
      hide();
    }
  });
  return {
    begin(text) {
      append("user", text);
      busy(true);
      status("小和正在回应…");
    },
    answer(text, model, truncated = false) {
      append("assistant", text);
      busy(false);
      status(`${model} · 记忆最近 6 轮${truncated ? " · 回答达到长度上限，可让小和继续" : ""}`);
    },
    error(text) {
      append("error", text);
      busy(false);
      status("请检查模型设置后重试。");
    },
    show,
    hide,
    busy,
    status,
    getState: () => ({ visible: !panel.hidden, pending, messages }),
  };
}
