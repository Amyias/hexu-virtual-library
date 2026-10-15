// Physical empty slots, not books. Importing or downloading supplies the bibliographic data.
export function expandInventory({ categories, books: rows }) {
  return rows.map(([shelf, side, layer, slot, color, x, y, z], index) => {
    const bookId = `HX-${String(index + 1).padStart(5, "0")}`;
    const locationCode = `S${shelf}-${side}-L${layer}-P${String(slot).padStart(3, "0")}`;
    return {
      title: "",
      author: "",
      category: categories[shelf - 1],
      shelf,
      side,
      layer,
      slot,
      color,
      keys: [bookId, bookId.replace("-", ""), locationCode],
      synopsis: "",
      bookId,
      chipId: bookId,
      locationCode,
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
