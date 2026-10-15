// The library's inventory. The one stored copy is public/models/book-inventory.json, written by
// tools/prepare-smart-books.mjs; the page, the tests, the local service and Blender all read it.
import inventory from "../../public/models/book-inventory.json" with { type: "json" };
import { expandInventory } from "./inventory.js";

export const books = expandInventory(inventory);
export const deferredSlotIds = inventory.library_deferred_ids;
export const anchors = [-6, -3, 0, 3, 6];
export const heights = [0.3, 0.7, 1.2, 1.7];
