import * as THREE from "three";

export function paintChip(ctx, b, x, y, w, h) {
  ctx.fillStyle = "#10231f";
  ctx.fillRect(x, y, w, h);
  ctx.textAlign = "center";
  ctx.fillStyle = "#e7e3bd";
  ctx.font = `600 ${h * 0.27}px monospace`;
  ctx.fillText(b.chipId, x + w / 2, y + h * 0.43);
  ctx.fillStyle = "#acc6ab";
  ctx.font = `${h * 0.19}px monospace`;
  ctx.fillText(b.locationCode, x + w / 2, y + h * 0.77);
}
export function chipTexture(b) {
  const c = document.createElement("canvas");
  c.width = 768;
  c.height = 384;
  paintChip(c.getContext("2d"), b, 0, 0, c.width, c.height);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** The shelved library: every volume is one Blender spine template, batched with GPU
 *  instancing. A bay holds as many spines as fit, so this runs to ten thousand instances
 *  rather than the eight hundred the cover-out display needed — which is why the shelf
 *  template is two mesh parts, and why nothing per-volume is drawn into a texture. */
export function createShelfBooks(scene, template, books) {
  template.updateMatrixWorld(true);
  // The template's local axes are the volume's own: X runs across the cover (into the shelf
  // now), Y is its height, Z its thickness — the axis a row packs along. A volume is shelved
  // spine to the aisle, so the quarter turns that used to face the cover at the reader are
  // gone: side A turns a half turn, side B none, and the spine comes out facing the aisle.
  const poses = books.map((b) =>
    new THREE.Matrix4().compose(
      new THREE.Vector3(...b.worldPosition),
      new THREE.Quaternion().setFromAxisAngle(
        new THREE.Vector3(0, 1, 0),
        b.side === "A" ? Math.PI : 0,
      ),
      new THREE.Vector3(b.widthScale ?? 1, b.heightScale ?? 1, b.depthScale ?? 1),
    ),
  );
  const zero = new THREE.Matrix4().makeScale(0, 0, 0);
  const pools = [];
  const visibleSlots = new Set(books.filter((b) => b.localBookId).map((b) => b.bookId));
  const pool = (mesh, matrices) => {
    matrices.forEach((m, i) => mesh.setMatrixAt(i, books[i].localBookId ? m : zero));
    scene.add(mesh);
    pools.push({ mesh, matrices });
  };
  books.forEach((b, i) => {
    b.origin = new THREE.Vector3(...b.worldPosition);
    b.instanceIndex = i;
  });
  template.traverse((part) => {
    if (!part.isMesh) return;
    const material = part.material.clone();
    // The cloth is the volume's own colour; the page edge above it keeps its paper tone.
    const cloth = /Spine/i.test(part.name);
    if (cloth) material.color.set("white");
    // A shelved volume casts nothing a reader can see: the shelf and the board above it already
    // cast the only shadow in there, and a book's own falls on the board it stands on.
    const instances = new THREE.InstancedMesh(part.geometry, material, books.length);
    instances.name = "ShelfBookInstances_" + part.name;
    instances.castShadow = false;
    instances.receiveShadow = true;
    instances.frustumCulled = false;
    const matrices = books.map((b, i) => {
      if (cloth) instances.setColorAt(i, new THREE.Color(b.color));
      return poses[i].clone().multiply(part.matrixWorld);
    });
    pool(instances, matrices);
  });
  // The highlight wraps the spine rather than the whole volume: at seventy volumes to a bay a
  // full-depth box would draw its wireframe through the books on either side.
  const highlight = new THREE.BoxHelper(
    new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.36, 0.05)),
    0xbdecc5,
  );
  highlight.visible = false;
  scene.add(highlight);
  return {
    get visibleCount() {
      return visibleSlots.size;
    },
    setVisible(b, visible) {
      visible = Boolean(visible && b.localBookId);
      if (visible) visibleSlots.add(b.bookId);
      else visibleSlots.delete(b.bookId);
      for (const { mesh, matrices } of pools) {
        mesh.setMatrixAt(b.instanceIndex, visible ? matrices[b.instanceIndex] : zero);
        mesh.instanceMatrix.needsUpdate = true;
      }
    },
    highlight(b, on) {
      highlight.visible = on;
      highlight.position.copy(b.origin);
      highlight.rotation.y = b.side === "A" ? Math.PI : 0;
      highlight.scale.set(b.widthScale ?? 1, b.heightScale ?? 1, b.depthScale ?? 1);
    },
    instancePools: pools.length,
  };
}
