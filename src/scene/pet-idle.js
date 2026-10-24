/* What 小和 does when nobody needs it: a little life of its own, visual only. The navigation
   anchor never moves; only the model inside it hops, looks around or gets sleepy.

   After REST seconds without any interaction it hops now and then and looks round the hall; at
   night (the moon in the window) it breathes slower, its eyes droop and it yawns. Pure and driven
   by time, so the same moment always looks the same and it can be tested without WebGL. */
export const REST = 12; // seconds of quiet before 小和 starts to amuse itself
const HOP_EVERY = 24,
  HOP_FOR = 0.7,
  LOOK_EVERY = 37,
  LOOK_FOR = 4,
  YAWN_EVERY = 45,
  YAWN_FOR = 2.4;

/** idleFor: seconds since the reader last did anything; night: the sky shows the moon. */
export function idleMotion(idleFor, night = false) {
  const motion = { mood: night ? "sleepy" : "idle", hop: 0, look: 0, eyes: 1, yawn: 0, breath: 1 };
  if (night) {
    motion.eyes = 0.45; // half-closed
    motion.breath = 0.6; // slower, deeper breathing
  }
  if (idleFor < REST) return motion;
  const t = idleFor - REST;
  motion.mood = night ? "sleepy" : "resting";
  const hop = t % HOP_EVERY;
  if (!night && hop < HOP_FOR) motion.hop = Math.sin((hop / HOP_FOR) * Math.PI) * 0.09;
  const look = t % LOOK_EVERY;
  if (look > LOOK_EVERY - LOOK_FOR)
    motion.look = Math.sin(((look - (LOOK_EVERY - LOOK_FOR)) / LOOK_FOR) * Math.PI * 2) * 0.6;
  const yawn = t % YAWN_EVERY;
  if (night && yawn < YAWN_FOR) {
    motion.yawn = Math.sin((yawn / YAWN_FOR) * Math.PI); // arms up, eyes shut, then back
    motion.eyes = 0.45 * (1 - motion.yawn);
  }
  return motion;
}
