/* The left Alt key as a voice shortcut, without the browser: a tap wakes 小和 like saying its
   name; a tap followed by a second press that is held is push-to-talk, recording from that press
   until the key is let go. Pure — the keyboard events, the clock and the timers come in from
   outside — so the gesture rules are tested apart from any page (tests/alt-gesture.test.mjs).

   Rules, in the order they matter:
   - Only AltLeft counts. On many layouts the right Alt is AltGr, which types characters.
   - Alt used with anything else (Alt+Tab, Alt+F4, Alt+click) is not a tap and cancels a
     recording in progress: the reader meant another shortcut.
   - A tap is a short press. It fires only once TAP_WINDOW has passed with no second press,
     because until then it may be the first half of push-to-talk.
   - Losing focus while recording cancels it: the key-up will never arrive. */

export const TAP_MAX = 400; // ms the first press may last and still be a tap
export const TAP_WINDOW = 300; // ms after a tap in which a second press starts push-to-talk
export const HOLD_MIN = 300; // ms a recording must last to be sent at all

export function createAltGesture({
  onTap,
  onHoldStart,
  onHoldEnd,
  now = () => Date.now(),
  setTimer = (fn, ms) => setTimeout(fn, ms),
  clearTimer = (id) => clearTimeout(id),
}) {
  // idle → first (key down) → waiting (released as a tap) → holding (second press)
  let state = "idle";
  let downAt = 0;
  let chord = false; // another key or the mouse was used while Alt was down
  let timer = null;

  function reset() {
    if (timer !== null) clearTimer(timer);
    timer = null;
    state = "idle";
    chord = false;
  }

  function cancelHold() {
    if (state === "holding") onHoldEnd({ cancelled: true, duration: now() - downAt });
    reset();
  }

  return {
    /** Feed a keydown. Returns true when the event is the shortcut's own, so the caller should
     *  stop the browser's default (Windows focuses the window menu on a bare Alt). */
    keydown(event) {
      if (event.code !== "AltLeft") {
        if (state === "holding") cancelHold();
        else if (state === "first") chord = true;
        else if (state === "waiting") reset();
        return false;
      }
      if (event.repeat) return true;
      if (state === "waiting") {
        clearTimer(timer);
        timer = null;
        state = "holding";
        downAt = now();
        onHoldStart();
        return true;
      }
      reset();
      state = "first";
      downAt = now();
      return true;
    },
    keyup(event) {
      if (event.code !== "AltLeft") return false;
      if (state === "holding") {
        const duration = now() - downAt;
        reset();
        onHoldEnd({ cancelled: duration < HOLD_MIN, duration });
        return true;
      }
      if (state === "first") {
        const tap = !chord && now() - downAt <= TAP_MAX;
        reset();
        if (tap) {
          state = "waiting";
          timer = setTimer(() => {
            timer = null;
            state = "idle";
            onTap();
          }, TAP_WINDOW);
        }
        return true;
      }
      return false;
    },
    /** The mouse was pressed: Alt+click is some other gesture. */
    pointerdown() {
      if (state === "first") chord = true;
      else if (state === "holding") cancelHold();
      else if (state === "waiting") reset();
    },
    /** The window lost focus; whatever was going on cannot finish. */
    blur() {
      if (state === "holding") cancelHold();
      else reset();
    },
    get holding() {
      return state === "holding";
    },
  };
}
