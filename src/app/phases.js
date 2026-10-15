/* The reading loop as an explicit state machine.

   One book at a time goes round a single cycle: the orb walks to the shelf, the book comes off it
   and flies to the reader, it is read, and it goes back. Every step is an animation that takes a
   second or more, and voice, buttons, keys and the pointer can all ask for something while one
   runs. The table below is the whole of what may happen next; anything else is refused, which is
   what keeps a second 「找三体」 from starting another walk mid-flight or a 「放回」 from returning a
   book that is still on its way.

     IDLE ──navigate──▶ NAVIGATING ──arrive──▶ PRESENTING ──present──▶ READING
       ▲                                                                  │
       └──────────────── shelve ──── RETURNING ◀──────── return ──────────┘ */
export const IDLE = "IDLE";
export const NAVIGATING = "NAVIGATING";
export const PRESENTING = "PRESENTING";
export const READING = "READING";
export const RETURNING = "RETURNING";

export const TRANSITIONS = Object.freeze({
  [IDLE]: Object.freeze({ navigate: NAVIGATING }),
  [NAVIGATING]: Object.freeze({ arrive: PRESENTING }),
  [PRESENTING]: Object.freeze({ present: READING }),
  [READING]: Object.freeze({ return: RETURNING }),
  [RETURNING]: Object.freeze({ shelve: IDLE }),
});

/** `send(event)` moves to the next phase and returns true, or refuses and returns false. */
export function createPhaseMachine(onChange = () => {}) {
  let phase = IDLE;
  return {
    get phase() {
      return phase;
    },
    is: (...phases) => phases.includes(phase),
    can: (event) => Object.hasOwn(TRANSITIONS[phase], event),
    send(event) {
      if (!Object.hasOwn(TRANSITIONS[phase], event)) return false;
      const previous = phase;
      phase = TRANSITIONS[phase][event];
      onChange(phase, previous, event);
      return true;
    },
  };
}
