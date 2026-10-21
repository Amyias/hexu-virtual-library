/* The sky follows the reader's local clock: the sun from 08:00 until 17:00, the moon otherwise.
   A manual choice on the toggle button only holds until the next of those two moments, so the
   room never gets stuck at night on a sunny morning. Pure functions, so they test without WebGL. */
export const DAY_START = 8;
export const NIGHT_START = 17;

export function isNightAt(date) {
  const hour = date.getHours();
  return hour < DAY_START || hour >= NIGHT_START;
}

/** The next 08:00 or 17:00 strictly after `date`, in local time. */
export function nextBoundary(date) {
  const next = new Date(date);
  next.setMinutes(0, 0, 0);
  const hour = date.getHours();
  if (hour < DAY_START) next.setHours(DAY_START);
  else if (hour < NIGHT_START) next.setHours(NIGHT_START);
  else {
    next.setDate(next.getDate() + 1);
    next.setHours(DAY_START);
  }
  return next;
}

/** A saved manual choice is honoured only until the boundary it was made before. */
export function readOverride(text, date) {
  try {
    const value = JSON.parse(text);
    if (typeof value?.night === "boolean" && Number.isFinite(value.until) && date < value.until)
      return value;
  } catch {}
  return null;
}
