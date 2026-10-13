/* The inventory as stored is compact: one row per volume, [shelf, side, layer, slot, colour,
   x, y, z], with the twelve named books recorded in full beside it. Everything else a book
   carries — its id, position code, search keys, chip payload, the placeholder title and
   synopsis — follows from the row and its index, so writing it out eleven thousand times only
   made a 12 MB module the page had to parse before the scene could start.

   Rows are in id order: the row at index i is HX-(i+1). tools/prepare-smart-books.mjs writes
   the file and checks that this expansion gives back exactly the books it laid out. */
export function expandInventory({ categories, placeholder, named, books: rows }) {
  return rows.map(([shelf, side, layer, slot, color, x, y, z], index) => {
    const bookId = `HX-${String(index + 1).padStart(5, "0")}`;
    const locationCode = `S${shelf}-${side}-L${layer}-P${String(slot).padStart(3, "0")}`;
    const demo = named[bookId];
    return {
      title: demo?.title ?? `馆藏 ${bookId}`,
      author: demo?.author ?? placeholder.author,
      category: demo?.category ?? categories[shelf - 1],
      shelf,
      side,
      layer,
      slot,
      color,
      keys: [...new Set([...(demo?.aliases ?? []), bookId, bookId.replace("-", ""), locationCode])],
      synopsis: demo?.synopsis ?? placeholder.synopsis,
      bookId,
      chipId: bookId,
      locationCode,
      placeholder: !demo,
      // Every volume is the template's own size; see tools/prepare-smart-books.mjs.
      widthScale: 1,
      heightScale: 1,
      depthScale: 1,
      worldPosition: [x, y, z],
      chipPayload: {
        book_id: bookId,
        shelf_id: `Shelf_${shelf}`,
        shelf_side: side,
        layer,
        slot,
        location_code: locationCode,
      },
    };
  });
}
