import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

/** The Blender pet owns its visual motion; the app owns the navigation anchor. */
export async function createCompanion(scene, home) {
  const gltf = await new GLTFLoader().loadAsync(
    new URL("../../public/models/xiaohe-pet.glb", import.meta.url).href,
  );
  const model = gltf.scene;
  const required = [
    "XiaoHePet",
    "PetBody",
    "PetEyeLeft",
    "PetEyeRight",
    "PetArmLeft",
    "PetArmRight",
    "PetLeg1",
    "PetLeg2",
    "PetLeg3",
    "PetLeg4",
  ];
  const parts = Object.fromEntries(
    required.map((name) => {
      const part = model.getObjectByName(name);
      if (!part) throw new Error("小和 Blender 模型缺少部件：" + name);
      return [name, part];
    }),
  );
  const root = new THREE.Group();
  root.name = "XiaoHeCompanion";
  root.position.copy(home);
  const visual = new THREE.Group();
  visual.name = "CompanionMotion";
  visual.add(model);
  root.add(visual);
  scene.add(root);
  const materials = new Set();
  let meshes = 0;
  model.traverse((object) => {
    if (!object.isMesh) return;
    meshes++;
    object.castShadow = true;
    object.receiveShadow = true;
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
      material.envMapIntensity = 0.3;
      materials.add(material);
    }
  });
  const eyes = [parts.PetEyeLeft, parts.PetEyeRight];
  const arms = [parts.PetArmLeft, parts.PetArmRight];
  const legs = [1, 2, 3, 4].map((n) => parts["PetLeg" + n]);
  const rings = [0, 1].map((index) => {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.335, 0.35, 64),
      new THREE.MeshBasicMaterial({
        color: index ? "#edb397" : "#d87656",
        transparent: true,
        opacity: 0,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = -0.282 + index * 0.003;
    ring.visible = false;
    root.add(ring);
    return ring;
  });
  let previousTime = 0,
    mode = "idle",
    lastPulse = 0;
  function update({ time, pulse, phase, camera }) {
    const dt = Math.min(0.1, Math.max(0, time - previousTime));
    previousTime = time;
    lastPulse = THREE.MathUtils.clamp(pulse, 0, 1);
    const travelling = ["NAVIGATING", "RETURNING"].includes(phase);
    mode = travelling ? "guiding" : lastPulse > 0.02 ? "awake" : "idle";
    // Its square face remains readable when the reader orbits the library.
    const yaw = Math.atan2(
      camera.position.x - root.position.x,
      camera.position.z - root.position.z,
    );
    const delta = Math.atan2(Math.sin(yaw - root.rotation.y), Math.cos(yaw - root.rotation.y));
    root.rotation.y += delta * (1 - Math.exp(-9 * dt));
    visual.position.y =
      Math.sin(time * 1.8) * 0.018 + lastPulse * (0.055 + 0.018 * Math.sin(time * 11));
    visual.rotation.z = Math.sin(time * (travelling ? 6 : 1.5)) * (travelling ? 0.055 : 0.015);
    const breath = Math.sin(time * 2) * 0.014;
    visual.scale.set(
      1 + breath + lastPulse * 0.13,
      1 - breath * 0.35 + lastPulse * 0.18,
      1 + lastPulse * 0.08,
    );
    const blink = time % 4.7 > 4.56 && lastPulse < 0.1 ? 0.12 : 1;
    eyes.forEach((eye) => {
      eye.scale.y = blink;
    });
    arms.forEach((arm, index) => {
      arm.rotation.z =
        (index ? -1 : 1) *
        (lastPulse * 0.38 +
          (travelling ? 0.16 : 0.025) * Math.sin(time * (travelling ? 7 : 2.2) + index));
    });
    legs.forEach((leg, index) => {
      leg.rotation.x =
        Math.sin(time * (travelling ? 11 : 1.8) + index * Math.PI) * (travelling ? 0.32 : 0.025);
    });
    for (const material of materials) {
      if (material.name.startsWith("Pet terracotta")) {
        material.emissive.set("#d87656");
        material.emissiveIntensity = lastPulse * 0.14;
      }
    }
    rings.forEach((ring, index) => {
      const wave = (time * 1.8 + index * 0.5) % 1;
      ring.visible = lastPulse > 0.025;
      ring.scale.setScalar(1 + wave * 1.4);
      ring.material.opacity = (1 - wave) * lastPulse * 0.6;
    });
  }
  return {
    root,
    update,
    getState: () => ({
      loaded: true,
      source: "blender",
      model: "xiaohe-pet.glb",
      style: "terracotta-pixel-pet",
      meshes,
      eyes: eyes.length,
      arms: arms.length,
      legs: legs.length,
      mode,
      pulse: lastPulse,
    }),
  };
}
