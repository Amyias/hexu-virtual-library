import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { createShelfBooks } from "./smart-books.js";

/** Blender is the sole source of the static environment; no primitive fallback. */
export async function loadEnvironment(scene, books, progress) {
  const url = new URL("../../public/models/hexu-library.glb", import.meta.url);
  const loader = new GLTFLoader();
  // The environment model is Draco-compressed; the decoder is vendored next to the other
  // dependencies, so nothing is fetched from a CDN. The decoder loads lazily, in a worker.
  const draco = new DRACOLoader();
  draco.setDecoderPath(new URL("../../public/vendor/draco/", import.meta.url).href);
  loader.setDRACOLoader(draco);
  const gltf = await loader.loadAsync(url.href, (event) => {
    /* The model is served gzip-compressed, and the browser counts `loaded` in decompressed bytes
       while `total` is the compressed Content-Length (6,419,828 over 6,042,972) — which the page
       used to announce as "正在加载 Blender 模型 106%". Clamped here rather than at the caller
       because this pair of numbers exists only here, and the number is a progress report rather
       than a measurement: the last stretch is the tail of one file arriving, not more than the
       whole of it. */
    if (event.total) progress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
  });
  let meshes = 0;
  gltf.scene.name = "BlenderLibrary";
  gltf.scene.traverse((object) => {
    if (!object.isMesh) return;
    meshes++;
    object.castShadow = true;
    object.receiveShadow = true;
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
      material.envMapIntensity = 0.38;
    }
  });
  scene.add(gltf.scene);
  // Two templates from the same Blender authoring frame: the hardcover with its chip pocket,
  // which the reader opens, and the thin spine-and-page-edge volume the shelves are stocked
  // with. Only the spine is visible on a shelved book, and a shelf holds ten thousand of them.
  const model = await loader.loadAsync(
    new URL("../../public/models/smart-book.glb", import.meta.url).href,
  );
  const bookTemplate = model.scene;
  const spines = await loader.loadAsync(
    new URL("../../public/models/shelf-book.glb", import.meta.url).href,
  );
  const shelfTemplate = spines.scene;
  const shelfBooks = createShelfBooks(scene, shelfTemplate, books);
  // Floating labels remain readable at any camera angle; physical brass plates are in the GLB.
  const names = ["计算机 / AI", "文学 / 历史", "经济 / 管理", "艺术 / 设计", "科幻 / 未来"];
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
    const response = await fetch(new URL("../../public/models/manifest.json", import.meta.url));
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
