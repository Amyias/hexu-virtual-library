/* Local settings stay in this window. The iframe owns its inputs and credentials;
   this module only opens/closes it and never reads form values. */
export function createSettingsPanel({ onClose = () => {} } = {}) {
  const dialog = document.createElement("dialog");
  dialog.id = "internalSettings";
  dialog.setAttribute("aria-labelledby", "internalSettingsTitle");
  dialog.innerHTML = `<div class="internal-settings-heading"><strong id="internalSettingsTitle">本机模型设置</strong><button type="button" autofocus aria-label="关闭设置并返回图书馆">返回图书馆 ×</button></div><div class="internal-settings-content"></div>`;
  document.body.append(dialog);
  const host = dialog.querySelector(".internal-settings-content");
  let frame = null,
    previousFocus = null;
  function close() {
    if (dialog.open) dialog.close();
  }
  function open() {
    if (dialog.open) return;
    previousFocus = document.activeElement;
    frame = document.createElement("iframe");
    frame.title = "本机设置：模型接入、密钥与更新";
    frame.src = "/settings?embedded=1";
    host.replaceChildren(frame);
    dialog.showModal();
  }
  dialog.querySelector("button").onclick = close;
  dialog.addEventListener("keydown", (event) => event.stopPropagation());
  dialog.addEventListener("close", () => {
    // Remove the settings document, including any unsaved password input, on every close.
    frame?.remove();
    frame = null;
    previousFocus?.isConnected && previousFocus.focus();
    onClose();
  });
  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[href]");
    if (
      !link ||
      event.button !== 0 ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !/^\/settings\/?$/.test(url.pathname)) return;
    event.preventDefault();
    open();
  });
  window.addEventListener("message", (event) => {
    if (
      event.origin === location.origin &&
      frame &&
      event.source === frame.contentWindow &&
      event.data?.type === "hexu-settings-close"
    )
      close();
  });
  return {
    open,
    close,
    get opened() {
      return dialog.open;
    },
    getState: () => ({ open: dialog.open }),
  };
}
