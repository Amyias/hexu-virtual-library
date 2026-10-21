import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { isNightAt, nextBoundary, readOverride } from "./sky-schedule.js";

const OVERRIDE = "hexu-sky-override"; // a manual choice and when it lapses
const LEGACY_PREFERENCE = "hexu-sky"; // 2.5.4 kept a permanent choice; the clock replaces it
const REQUIRED = [
  "PixelSun",
  "PixelSunDisc",
  "PixelSunRays",
  "PixelMoon",
  "PixelMoonFace",
  "PixelMoonStars",
];

/* The Blender pixel sun hangs outside the second arched window, on the same compass bearing as
   the window daylight, so the floor shadows point away from it. Its height is lowered from the
   light's true elevation (~32°, which would sit above every overview frame) until it shows through
   the glass. The moon takes the same spot; lighting.setNight keeps the light direction unchanged. */
const DURATION = 1.4; // seconds of wall-clock time, however slowly frames arrive

export async function createSky({
  scene,
  lighting,
  rig,
  storage = globalThis.localStorage,
  now = () => performance.now() / 1000,
  clock = () => new Date(),
  onChange = () => {},
}) {
  const gltf = await new GLTFLoader().loadAsync(
    new URL("../../public/models/celestial.glb", import.meta.url).href,
  );
  const parts = Object.fromEntries(
    REQUIRED.map((name) => {
      const part = gltf.scene.getObjectByName(name);
      if (!part) throw new Error("天体 Blender 模型缺少部件：" + name);
      return [name, part];
    }),
  );
  // Flat pixel colours: unlit, untouched by tone mapping and fog, never casting shadows.
  gltf.scene.traverse((object) => {
    if (!object.isMesh) return;
    object.castShadow = object.receiveShadow = false;
    const swap = (material) =>
      new THREE.MeshBasicMaterial({
        name: material.name,
        color: material.color,
        fog: false,
        toneMapped: false,
      });
    object.material = Array.isArray(object.material)
      ? object.material.map(swap)
      : swap(object.material);
  });
  const root = new THREE.Group();
  root.name = "Sky bodies";
  root.position.fromArray(rig.sky.position);
  const sun = parts.PixelSun,
    moon = parts.PixelMoon;
  root.add(sun, moon);
  scene.add(root);

  const blend = { value: 0 };
  let night = false;
  let transition = null; // { from, to, start }
  function apply() {
    const v = blend.value;
    // The sun sinks and shrinks away, then the moon rises into the same window.
    const sunScale = Math.max(0, 1 - 2 * v),
      moonScale = Math.max(0, 2 * v - 1);
    sun.visible = sunScale > 0;
    moon.visible = moonScale > 0;
    sun.scale.setScalar(Math.max(sunScale, 1e-4));
    moon.scale.setScalar(Math.max(moonScale, 1e-4));
    sun.position.y = -0.6 * Math.min(1, 2 * v);
    moon.position.y = -0.6 * Math.min(1, 2 - 2 * v);
    lighting.setNight(v);
  }
  let override = null; // { night, until } while a manual choice holds
  function remember(value) {
    override = value;
    try {
      if (value) storage?.setItem(OVERRIDE, JSON.stringify(value));
      else storage?.removeItem(OVERRIDE);
    } catch {}
  }
  function set(next, animate = true) {
    night = Boolean(next);
    const to = night ? 1 : 0;
    // Driven by elapsed time in update(), not a tween: GSAP's lag smoothing would stretch the
    // change over many seconds on a slow GPU.
    transition = animate && blend.value !== to ? { from: blend.value, to, start: now() } : null;
    if (!transition) {
      blend.value = to;
      apply();
    }
    return night;
  }
  try {
    storage?.removeItem(LEGACY_PREFERENCE);
    override = readOverride(storage?.getItem(OVERRIDE), clock());
  } catch {}
  if (!override) remember(null);
  set(override ? override.night : isNightAt(clock()), false);

  let nextCheck = 0;
  /** Once a second: lapse an expired manual choice, then follow the clock. */
  function follow() {
    const date = clock();
    if (override && date >= override.until) remember(null);
    const scheduled = override ? override.night : isNightAt(date);
    if (scheduled === night) return;
    set(scheduled);
    onChange({ night, automatic: true });
  }

  return {
    root,
    /** Manual switch; it holds until the next 08:00 or 17:00, then the clock takes over. */
    toggle() {
      const date = clock();
      const next = !night;
      remember(next === isNightAt(date) ? null : { night: next, until: +nextBoundary(date) });
      set(next);
      onChange({ night, automatic: false });
      return night;
    },
    get night() {
      return night;
    },
    get manualUntil() {
      return override ? new Date(override.until) : null;
    },
    update({ time, camera }) {
      if (now() >= nextCheck) {
        nextCheck = now() + 1;
        follow();
      }
      if (transition) {
        const t = Math.min(1, (now() - transition.start) / DURATION);
        const eased = 0.5 - 0.5 * Math.cos(Math.PI * t);
        blend.value = transition.from + (transition.to - transition.from) * eased;
        apply();
        if (t === 1) transition = null;
      }
      // Yaw only: the pixel face turns toward the viewer and stays upright.
      root.rotation.y = Math.atan2(
        camera.position.x - root.position.x,
        camera.position.z - root.position.z,
      );
      parts.PixelSunRays.scale.setScalar(1 + 0.05 * Math.sin(time * 1.6));
      parts.PixelMoonStars.visible = Math.sin(time * 2.3) > -0.8;
    },
    getState: () => ({
      night,
      automatic: !override,
      manualUntil: override?.until ?? null,
      blend: blend.value,
      position: root.position.toArray(),
      sunVisible: sun.visible,
      moonVisible: moon.visible,
    }),
  };
}
