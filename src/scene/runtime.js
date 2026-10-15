import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
export function createRuntime(canvas) {
  // Scene uses metres. Shelf local dimensions 1 (X) × 2 (Y) × 8 (Z).
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
    });
  } catch (e) {
    throw new Error("无法启动 WebGL，请启用硬件加速。");
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(innerWidth, innerHeight);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#e9ece3");
  scene.fog = new THREE.Fog("#e9ece3", 36, 70);
  const camera = new THREE.PerspectiveCamera(39, innerWidth / innerHeight, 0.1, 100);
  const focus = new THREE.Vector3(0, 0, -1.2);
  const orbit = { angle: 0.44, elevation: 0.65, radius: 26 };
  function updateCamera() {
    camera.position.set(
      focus.x + Math.sin(orbit.angle) * Math.cos(orbit.elevation) * orbit.radius,
      focus.y + Math.sin(orbit.elevation) * orbit.radius,
      focus.z + Math.cos(orbit.angle) * Math.cos(orbit.elevation) * orbit.radius,
    );
    camera.lookAt(focus);
  }
  updateCamera();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x899276, 1.65));
  const sun = new THREE.DirectionalLight(0xfff4df, 3.0);
  sun.position.set(-8, 18, 10);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, {
    left: -17,
    right: 17,
    top: 17,
    bottom: -17,
    near: 1,
    far: 60,
  });
  sun.shadow.bias = -0.0005;
  sun.shadow.normalBias = 0.035;
  scene.add(sun);

  const pmrem = new THREE.PMREMGenerator(renderer);
  const environment = new RoomEnvironment();
  const envTarget = pmrem.fromScene(environment, 0.06);
  scene.environment = envTarget.texture;
  environment.dispose();
  pmrem.dispose();
  return { renderer, scene, camera, focus, orbit, updateCamera };
}
