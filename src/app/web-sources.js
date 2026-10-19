/** Treat model/tool metadata as untrusted text; only public HTTP links are clickable. */
export function sourceEntries(sources) {
  if (!Array.isArray(sources)) return [];
  return sources.slice(0, 8).flatMap((source) => {
    try {
      if (!source || typeof source.url !== "string") return [];
      const url = new URL(source.url);
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return [];
      return [
        { url: url.href, title: String(source.title || url.hostname).slice(0, 180), id: source.id },
      ];
    } catch {
      return [];
    }
  });
}

export function renderSources(host, sources) {
  host.replaceChildren();
  const entries = sourceEntries(sources);
  host.hidden = entries.length === 0;
  for (const [index, source] of entries.entries()) {
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.referrerPolicy = "no-referrer";
    link.textContent = `[${Number.isInteger(source.id) ? source.id : index + 1}] ${source.title}`;
    link.title = source.url;
    host.append(link);
  }
}
