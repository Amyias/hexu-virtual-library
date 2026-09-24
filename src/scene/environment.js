import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { createShelfBooks } from './smart-books.js';

/** Blender is the sole source of the static environment; no primitive fallback. */
export async function loadEnvironment(scene, books, progress) {
  const url = new URL("../../public/models/hexu-library.glb", import.meta.url);
  const loader = new GLTFLoader();
  const gltf = await loader.loadAsync(url.href, (event) => {
    if (event.total) progress(Math.round((event.loaded / event.total) * 100));
  });
  let meshes = 0;
  gltf.scene.name = "BlenderLibrary";
  gltf.scene.traverse((object) => {
    if (!object.isMesh) return;
    meshes++;
    object.castShadow = true;
    object.receiveShadow = true;
    for (const material of Array.isArray(object.material)
      ? object.material
      : [object.material]) {
      material.envMapIntensity = 0.38;
    }
  });
  scene.add(gltf.scene);
  const model=await loader.loadAsync(new URL('../../public/models/smart-book.glb',import.meta.url).href);
  const bookTemplate=model.scene;
  const shelfBooks=createShelfBooks(scene,bookTemplate,books);
  // Floating labels remain readable at any camera angle; physical brass plates are in the GLB.
  const names = [
    "计算机 / AI",
    "文学 / 历史",
    "经济 / 管理",
    "艺术 / 设计",
    "科幻 / 未来",
  ];
  names.forEach((name, i) => {
    const canvas = document.createElement("canvas");
    canvas.width = 768;
    canvas.height = 128;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#324a39";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = '500 42px "Microsoft YaHei",sans-serif';
    ctx.fillText(`0${i + 1}  ${name}`, 384, 64);
    const map = new THREE.CanvasTexture(canvas);
    map.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ map, depthWrite: false, toneMapped: false }),
    );
    sprite.position.set((i - 2) * 3, 2.3, -0.65);
    sprite.scale.set(2.35, 0.39, 1);
    scene.add(sprite);
  });
  let staticBooks = 0;
  try {
    const response = await fetch(
      new URL("../../public/models/manifest.json", import.meta.url),
    );
    if (response.ok) staticBooks = (await response.json()).static_books;
  } catch {
    /* Model remains usable if optional statistics are missing. */
  }
  return {
    loaded: true,
    meshes,
    staticBooks,
    root: gltf.scene,
    bookTemplate,
    shelfBooks,
  };
}
