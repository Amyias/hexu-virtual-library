// World-to-screen projection shared by the 3D companion's dialogue overlay.
export function projectDialogueAnchor(camera, anchor, offset, target) {
  // lookAt changes the quaternion after updating matrixWorld. Pointer events and GSAP can
  // therefore leave matrixWorldInverse one pose behind until WebGLRenderer runs later.
  // Sync here so the HTML overlay and the rendered scene always use the same camera pose.
  camera.updateWorldMatrix(true, false);
  return target.copy(anchor).add(offset).project(camera);
}

/** Place the existing auto-sized bubble without covering the companion's projected bounds. */
export function placeDialogue({
  viewWidth,
  viewHeight,
  bubbleWidth,
  bubbleHeight,
  anchorX,
  anchorY,
  pet,
  pinned = false,
  previous = "above",
}) {
  const margin = 16,
    gap = 24;
  const clamp = (value, low, high) => Math.max(low, Math.min(value, Math.max(low, high)));
  const width = bubbleWidth;
  const height = Math.min(bubbleHeight, viewHeight - margin * 2);
  const center = clamp(anchorX, width / 2 + margin, viewWidth - width / 2 - margin);
  const overlaps = (left, bottom, h) =>
    pet &&
    left + width / 2 > pet.left - gap &&
    left - width / 2 < pet.right + gap &&
    bottom > pet.top - gap &&
    bottom - h < pet.bottom + gap;
  const result = (left, top, maxHeight, placement) => ({
    left,
    top,
    maxHeight,
    placement,
    tail: clamp(anchorX - left + width / 2, 16, width - 16),
  });
  if (pinned || !pet) {
    const left = pinned ? viewWidth - width / 2 - 20 : center;
    const top = pinned ? viewHeight - 24 : clamp(anchorY, height + margin, viewHeight - margin);
    if (!overlaps(left, top, height)) return result(left, top, height, pinned ? "pinned" : "above");
  }
  const aboveBottom = Math.min(anchorY, pet.top - gap);
  const aboveSpace = aboveBottom - margin;
  // A small reserve prevents idle breathing from alternating above/side at the boundary.
  if (aboveSpace >= height + (previous === "above" ? 0 : 16))
    return result(center, aboveBottom, height, "above");
  const rightSpace = viewWidth - margin - pet.right - gap;
  const leftSpace = pet.left - gap - margin;
  const bottom = clamp((pet.top + pet.bottom + height) / 2, height + margin, viewHeight - margin);
  if (previous === "left" && leftSpace >= width)
    return result(pet.left - gap - width / 2, bottom, height, "left");
  if (rightSpace >= width) return result(pet.right + gap + width / 2, bottom, height, "right");
  if (leftSpace >= width) return result(pet.left - gap - width / 2, bottom, height, "left");
  const belowSpace = viewHeight - margin - pet.bottom - gap;
  if (belowSpace >= aboveSpace) {
    const available = Math.max(1, Math.min(height, belowSpace));
    return result(center, pet.bottom + gap + available, available, "below");
  }
  const available = Math.max(1, Math.min(height, aboveSpace));
  return result(center, aboveBottom, available, "above");
}
