// SVG displacement technique inspired by Shu Ding's liquid-glass (MIT, 2025).
// https://github.com/shuding/liquid-glass — see LIQUID_GLASS_LICENSE.txt.
// This lens uses CSS-pixel distances: wide reading bars and compact players have
// the same rounded rim, without stretching the corners or warping the text.
export function createLensMap(width, height, radius = 28) {
  if (!(width > 0 && height > 0)) return null;
  const ratio = Math.min(1, 1024 / width, 256 / height);
  const w = Math.max(1, Math.round(width * ratio));
  const h = Math.max(1, Math.round(height * ratio));
  const pixels = new Uint8ClampedArray(w * h * 4);
  const r = Math.min(radius, width / 2, height / 2);
  const rim = Math.min(22, height / 3);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const px = ((x + 0.5) / w - 0.5) * width;
      const py = ((y + 0.5) / h - 0.5) * height;
      const qx = Math.abs(px) - width / 2 + r;
      const qy = Math.abs(py) - height / 2 + r;
      const cx = Math.max(qx, 0),
        cy = Math.max(qy, 0);
      const length = Math.hypot(cx, cy);
      const distance = -(Math.min(Math.max(qx, qy), 0) + length - r);
      let nx = 0,
        ny = 0;
      if (length > 0) {
        nx = (cx / length) * Math.sign(px);
        ny = (cy / length) * Math.sign(py);
      } else if (qx > qy) nx = Math.sign(px);
      else ny = Math.sign(py);
      const t = Math.max(0, Math.min(1, distance / rim));
      const bend = distance >= 0 ? Math.pow(1 - t, 2) : 0;
      const i = (y * w + x) * 4;
      pixels[i] = Math.round(128 - nx * bend * 112);
      pixels[i + 1] = Math.round(128 - ny * bend * 112);
      pixels[i + 2] = 128;
      pixels[i + 3] = 255;
    }
  }
  return { width: w, height: h, pixels };
}

let serial = 0;
export function attachMusicGlass(panel) {
  const id = `music-lens-${++serial}`;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "music-glass-defs");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = `<defs><filter id="${id}" filterUnits="userSpaceOnUse" x="0" y="0" color-interpolation-filters="sRGB">
    <feImage result="lens" preserveAspectRatio="none"/>
    <feDisplacementMap in="SourceGraphic" in2="lens" scale="30" xChannelSelector="R" yChannelSelector="G" result="refracted"/>
    <feDisplacementMap in="SourceGraphic" in2="lens" scale="32" xChannelSelector="R" yChannelSelector="G"/>
    <feColorMatrix type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="red"/>
    <feColorMatrix in="refracted" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 1 0" result="cyan"/>
    <feBlend in="red" in2="cyan" mode="screen"/>
  </filter></defs>`;
  document.body.append(svg);
  const filter = svg.querySelector("filter");
  const image = svg.querySelector("feImage");
  const canvas = document.createElement("canvas");
  let size = "",
    frame = 0;
  function refresh() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const { width, height } = panel.getBoundingClientRect();
      if (!width || !height || panel.hidden) return;
      const next = `${Math.round(width)}:${Math.round(height)}`;
      if (size === next) return;
      const map = createLensMap(width, height);
      canvas.width = map.width;
      canvas.height = map.height;
      canvas.getContext("2d").putImageData(new ImageData(map.pixels, map.width, map.height), 0, 0);
      for (const element of [filter, image]) {
        element.setAttribute("width", width);
        element.setAttribute("height", height);
      }
      image.setAttribute("href", canvas.toDataURL());
      panel.style.setProperty("--music-lens", `url(#${id})`);
      panel.dataset.glassSize = next;
      size = next;
    });
  }
  const observer = new ResizeObserver(refresh);
  observer.observe(panel);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  panel.addEventListener("pointermove", (event) => {
    if (reduced.matches) return;
    const rect = panel.getBoundingClientRect();
    panel.style.setProperty("--music-light-x", `${event.clientX - rect.left}px`);
    panel.style.setProperty("--music-light-y", `${event.clientY - rect.top}px`);
  });
  panel.addEventListener("pointerleave", () => {
    panel.style.removeProperty("--music-light-x");
    panel.style.removeProperty("--music-light-y");
  });
  return { refresh };
}
