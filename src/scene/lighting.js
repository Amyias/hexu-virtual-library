import * as THREE from "three";

/** Window daylight, actual luminaire emitters and Blender-baked ground occlusion. */
export async function createLighting({ scene, renderer, root }) {
  const response = await fetch(new URL("../../public/models/lighting-rig.json", import.meta.url));
  if (!response.ok) throw new Error("无法加载馆内灯光配置");
  const rig = await response.json();
  const group = new THREE.Group();
  group.name = "Library lighting";
  scene.add(group);
  group.add(new THREE.HemisphereLight("#d9e6ff", "#79634b", 0.7));
  const bounce = new THREE.DirectionalLight("#dce8ff", 0.7);
  bounce.position.set(0, 9, 8);
  group.add(bounce);
  const sun = new THREE.DirectionalLight("#fff0d9", rig.sun.intensity);
  sun.name = "Window daylight";
  sun.position.fromArray(rig.sun.position);
  sun.target.position.fromArray(rig.sun.target);
  sun.castShadow = true;
  const resolution = Math.min(renderer.capabilities.maxTextureSize, innerWidth < 800 ? 2048 : 4096);
  sun.shadow.mapSize.set(resolution, resolution);
  Object.assign(sun.shadow.camera, {
    left: -14,
    right: 14,
    top: 13,
    bottom: -13,
    near: 1,
    far: 45,
  });
  sun.shadow.bias = -0.00008;
  sun.shadow.normalBias = 0.007;
  sun.shadow.radius = 3;
  group.add(sun, sun.target);

  const pendantShadows = [];
  for (const [index, position] of rig.pendants.entries()) {
    const lamp = new THREE.SpotLight("#ffe1aa", 12, 8, 0.87, 0.65, 2);
    lamp.name = `Pendant light ${index + 1}`;
    lamp.position.fromArray(position);
    lamp.target.position.set(position[0], 0, position[2]);
    lamp.castShadow = true;
    lamp.shadow.mapSize.set(512, 512);
    lamp.shadow.camera.near = 0.12;
    lamp.shadow.camera.far = 8;
    lamp.shadow.bias = -0.0001;
    lamp.shadow.normalBias = 0.004;
    lamp.shadow.radius = 3;
    lamp.shadow.autoUpdate = false;
    lamp.shadow.needsUpdate = true;
    pendantShadows.push(lamp.shadow);
    group.add(lamp, lamp.target);
  }
  for (const position of rig.tables) {
    const lamp = new THREE.PointLight("#ffdfa3", 0.65, 1.7, 2);
    lamp.position.fromArray(position);
    group.add(lamp);
  }

  const ao = await new THREE.TextureLoader().loadAsync(
    new URL("../../public/textures/library-contact-ao.png", import.meta.url).href,
  );
  ao.channel = 1;
  ao.colorSpace = THREE.NoColorSpace;
  const anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  const point = new THREE.Vector3();
  let receivers = 0;
  let underlayVertices = 0;
  root.updateMatrixWorld(true);
  root.traverse((object) => {
    if (!object.isMesh) return;
    let materials = Array.isArray(object.material) ? object.material : [object.material];
    // The stone foundation also contains the exposed window sills in the same material
    // batch. Only its hidden top under the planks gets the dark underlay finish; otherwise
    // bright stone leaks through every 8 mm board joint under unshadowed sky illumination.
    if (object.userData.name === "01 Architecture__Warm honed limestone") {
      // Other groups (including the service counter) share this GLTF material but have
      // no vertex colour attribute. Isolate the finish before enabling vertex colours.
      materials = materials.map((material) => material.clone());
      object.material = Array.isArray(object.material) ? materials : materials[0];
      const positions = object.geometry.getAttribute("position");
      const colors = new Float32Array(positions.count * 3).fill(1);
      for (let i = 0; i < positions.count; i++) {
        point.fromBufferAttribute(positions, i).applyMatrix4(object.matrixWorld);
        if (point.y < -0.015 && point.y > -0.055) {
          colors.fill(0.035, i * 3, i * 3 + 3);
          underlayVertices++;
        }
      }
      object.geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      for (const material of materials) material.vertexColors = true;
    }
    for (const material of materials) {
      material.envMapIntensity = material.metalness > 0.5 ? 0.55 : 0.22;
      for (const texture of [material.map, material.normalMap, material.roughnessMap]) {
        if (texture) texture.anisotropy = anisotropy;
      }
      if (material.name === "Warm opal luminaire") material.emissiveIntensity = 3;
      if (!material.name.startsWith("Oak floor")) continue;
      const positions = object.geometry.getAttribute("position");
      const uv = new Float32Array(positions.count * 2);
      for (let i = 0; i < positions.count; i++) {
        point.fromBufferAttribute(positions, i).applyMatrix4(object.matrixWorld);
        uv[2 * i] = (point.x - rig.ground.minX) / (rig.ground.maxX - rig.ground.minX);
        uv[2 * i + 1] = (rig.ground.maxZ - point.z) / (rig.ground.maxZ - rig.ground.minZ);
      }
      object.geometry.setAttribute("uv1", new THREE.BufferAttribute(uv, 2));
      material.aoMap = ao;
      material.aoMapIntensity = 0.85;
      material.normalScale.multiplyScalar(0.45);
      material.needsUpdate = true;
      receivers++;
    }
  });
  let dynamicShadows = false;
  return {
    setDynamicShadows(moving) {
      if (moving === dynamicShadows) return;
      dynamicShadows = moving;
      for (const shadow of pendantShadows) {
        shadow.autoUpdate = moving;
        shadow.needsUpdate = true;
      }
    },
    getState: () => ({
      sunFromWindow: true,
      shadowMapSize: resolution,
      pendantLights: rig.pendants.length,
      tableLights: rig.tables.length,
      groundAoReceivers: receivers,
      groundAoResolution: [ao.image.width, ao.image.height],
      underlayVertices,
      cachedPendantShadows: !dynamicShadows,
    }),
  };
}
