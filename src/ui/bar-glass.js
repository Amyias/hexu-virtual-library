/* The glass the top bar is made of.

A frosted bar is a blur and a tint. What makes Apple's material read as glass is that the edge
*bends* what is behind it: the middle is flat, and within a few pixels of the rim the backdrop is
displaced towards the inside, like the rim of a lens. That is the part this module builds.

The bend is fed to CSS as an SVG displacement filter, which the stylesheet composes with a blur
and a saturation. The filter needs a normal map, so one is drawn here on a canvas for the bar's
actual size — a rounded rectangle with square top corners and rounded bottom ones, matching the
bar's own radius — and handed to `feImage` as a data URL. Nothing about the map is guessed from
constants: the geometry comes from the element, and it is redrawn when the window changes size.

Two honest limits. It is a screen-space lens: it displaces pixels of the backdrop without knowing
anything about the depth of what they show. And it is Chromium-only — a browser without
`backdrop-filter: url(#…)` gets the blur and the rim, minus the bending, which is what the
fallback class is for.

Fallback aside, nothing here is required for the page to work: if any of it fails, the bar is
still a bar.
*/

/** The map is stretched over the element, so it does not need the bar's full resolution. */
const MAP_MAX = { width: 1024, height: 64 };
/** How far the bend reaches in from the edge, in CSS pixels. A title bar is thin, so it is small. */
const BEND_WIDTH = 7;
/** Height of the lensed strip along the bar's bottom edge, in CSS pixels.

    The bend is an edge effect: it only exists within a few pixels of the rim. Applying the
    displacement to the whole bar therefore spends most of its cost on the middle, where the
    backdrop is displaced by nothing. Lensing a strip instead cuts the filtered area by about four
    times and puts it where the library actually passes under the bar. The bar itself keeps an
    ordinary blur, which the compositor handles for free. */
const STRIP_HEIGHT = 16;
/** The lens strength handed to feDisplacementMap. */
const DISPLACE = 26;
/** Corner radius of the bar's bottom corners, matching the stylesheet. */
const RADIUS = 18;

export function createBarGlass(bar) {
  const strip = document.createElement("div");
  strip.className = "bar-lens";
  strip.setAttribute("aria-hidden", "true");
  bar.appendChild(strip);

  const lensId = "barLens";
  let enabled = true;
  let pending = 0;

  const supportsLens =
    typeof CSS !== "undefined" &&
    typeof CSS.supports === "function" &&
    CSS.supports("backdrop-filter", "url(#barLens)");

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "0");
  svg.setAttribute("height", "0");
  svg.setAttribute("aria-hidden", "true");
  svg.style.position = "absolute";
  svg.style.pointerEvents = "none";

  const filter = document.createElementNS("http://www.w3.org/2000/svg", "filter");
  filter.setAttribute("id", lensId);
  filter.setAttribute("x", "0");
  filter.setAttribute("y", "0");
  filter.setAttribute("width", "100%");
  filter.setAttribute("height", "100%");
  // Straight (non-premultiplied) interpolation matters: the displacement values are data, not
  // light, and gamma-correcting them would bend the backdrop unevenly.
  filter.setAttribute("color-interpolation-filters", "sRGB");

  const image = document.createElementNS("http://www.w3.org/2000/svg", "feImage");
  image.setAttribute("result", "map");
  image.setAttribute("x", "0");
  image.setAttribute("y", "0");
  image.setAttribute("width", "100%");
  image.setAttribute("height", "100%");
  image.setAttribute("preserveAspectRatio", "none");

  const displace = document.createElementNS("http://www.w3.org/2000/svg", "feDisplacementMap");
  displace.setAttribute("in", "SourceGraphic");
  displace.setAttribute("in2", "map");
  displace.setAttribute("scale", String(DISPLACE));
  displace.setAttribute("xChannelSelector", "R");
  displace.setAttribute("yChannelSelector", "G");

  filter.append(image, displace);
  svg.appendChild(filter);
  document.body.appendChild(svg);

  /** Distance from a point to the bar's outline, with the bottom corners rounded. */
  function distanceInside(x, y, width, height, radius) {
    const inBottomCorner = y > height - radius && (x < radius || x > width - radius);
    if (inBottomCorner) {
      const centreX = x < radius ? radius : width - radius;
      return radius - Math.hypot(x - centreX, y - (height - radius));
    }
    return Math.min(x, width - x, y, height - y);
  }

  /** Draw the normal map: flat in the middle, bending inward within BEND_WIDTH of the rim. */
  function paint() {
    const width = Math.max(1, Math.round(strip.clientWidth || bar.clientWidth));
    const height = Math.max(1, Math.round(strip.clientHeight || STRIP_HEIGHT));
    const columns = Math.max(16, Math.min(MAP_MAX.width, Math.round(width / 2)));
    const rows = Math.max(8, Math.min(MAP_MAX.height, Math.round(height / 2)));

    const canvas = document.createElement("canvas");
    canvas.width = columns;
    canvas.height = rows;
    const context = canvas.getContext("2d");
    const pixels = context.createImageData(columns, rows);
    const stepX = width / columns;
    const stepY = height / rows;

    for (let row = 0; row < rows; row++) {
      for (let column = 0; column < columns; column++) {
        const x = (column + 0.5) * stepX;
        const y = (row + 0.5) * stepY;
        const distance = distanceInside(x, y, width, height, RADIUS);
        const bend = Math.max(0, Math.min(1, (BEND_WIDTH - distance) / BEND_WIDTH));

        // Inward normal from the gradient of the distance field — the corner arcs come out right
        // without a second special case.
        const epsilon = stepX * 0.75;
        const gradientX =
          distanceInside(x + epsilon, y, width, height, RADIUS) -
          distanceInside(x - epsilon, y, width, height, RADIUS);
        const gradientY =
          distanceInside(x, y + epsilon, width, height, RADIUS) -
          distanceInside(x, y - epsilon, width, height, RADIUS);
        const length = Math.hypot(gradientX, gradientY) || 1;

        const index = (row * columns + column) * 4;
        pixels.data[index] = 128 + (gradientX / length) * bend * 127;
        pixels.data[index + 1] = 128 + (gradientY / length) * bend * 127;
        pixels.data[index + 2] = 128;
        pixels.data[index + 3] = 255;
      }
    }

    context.putImageData(pixels, 0, 0);
    image.setAttribute("href", canvas.toDataURL());
  }

  function apply() {
    if (!supportsLens || !enabled) {
      strip.style.removeProperty("backdrop-filter");
      bar.classList.remove("glass-lens");
      return;
    }
    paint();
    strip.style.backdropFilter = `url(#${lensId}) blur(3px) saturate(180%) brightness(1.04)`;
    bar.classList.add("glass-lens");
  }

  function refresh() {
    // Coalesced through a frame: resizing the window fires this faster than the map needs
    // rebuilding, and each rebuild rasterises a canvas.
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(apply);
  }

  const observer = new ResizeObserver(refresh);
  observer.observe(bar);
  observer.observe(strip);
  apply();

  return {
    refresh,
    /** Turning the lens off leaves the blur and the rim — used to measure what the lens costs. */
    setEnabled(value) {
      enabled = Boolean(value);
      apply();
      return enabled;
    },
    get enabled() {
      return enabled && supportsLens;
    },
  };
}
