import * as THREE from "three";

/* Tweens as promises, so a choreography reads as a sequence of awaits, plus the dashed route the
   orb draws from the front desk to the shelf. */
export function createMotion({ gsap, scene, camera, focus, home }) {
  const routeMaterial = new THREE.LineDashedMaterial({
    color: "#86a58c",
    dashSize: 0.13,
    gapSize: 0.12,
    transparent: true,
    opacity: 0.7,
  });
  let route = null;

  function moveTo(object, position, duration = 1.5, extra = {}) {
    return new Promise((resolve) =>
      gsap.to(object, {
        x: position.x,
        y: position.y,
        z: position.z,
        duration,
        ease: "power2.inOut",
        ...extra,
        onComplete: resolve,
      }),
    );
  }

  function tween(target, vars) {
    return new Promise((resolve) => gsap.to(target, { ...vars, onComplete: resolve }));
  }

  function cameraTo(position, target, duration = 1.7) {
    return Promise.all([
      moveTo(camera.position, position, duration),
      moveTo(focus, target, duration, { onUpdate: () => camera.lookAt(focus) }),
    ]).then(() => camera.lookAt(focus));
  }

  function clearRoute() {
    if (!route) return;
    scene.remove(route);
    route.geometry.dispose();
    route = null;
  }

  function showRoute(target) {
    clearRoute();
    const curve = new THREE.CatmullRomCurve3([
      home.clone(),
      new THREE.Vector3(home.x, 1.7, 3.3),
      new THREE.Vector3(target.x, target.y + 1, 1.9),
      target,
    ]);
    route = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(80)), routeMaterial);
    route.computeLineDistances();
    scene.add(route);
  }

  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  return { moveTo, tween, cameraTo, showRoute, clearRoute, pause };
}
