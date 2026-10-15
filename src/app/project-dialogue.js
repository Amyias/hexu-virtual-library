// World-to-screen projection shared by the 3D companion's dialogue overlay.
export function projectDialogueAnchor(camera, anchor, offset, target) {
  // lookAt changes the quaternion after updating matrixWorld. Pointer events and GSAP can
  // therefore leave matrixWorldInverse one pose behind until WebGLRenderer runs later.
  // Sync here so the HTML overlay and the rendered scene always use the same camera pose.
  camera.updateWorldMatrix(true, false);
  return target.copy(anchor).add(offset).project(camera);
}
