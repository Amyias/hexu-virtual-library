// Preserve the persisted library slot -> physical chip mapping across the removal of presets.
// Earlier releases allocated literature first, skipping the IDs in library_deferred_ids.
// Those IDs now become usable at the end; existing slot numbers never change.
export function orderedShelfSlots(slots, deferredIds) {
  const deferred = new Set(deferredIds.map((id) => `HX-${String(id).padStart(5, "0")}`));
  return [
    ...slots
      .filter((slot) => !deferred.has(slot.bookId))
      .sort((a, b) => Number(b.shelf === 2) - Number(a.shelf === 2)),
    ...slots.filter((slot) => deferred.has(slot.bookId)),
  ];
}
