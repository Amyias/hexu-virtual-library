"""Remove preset shelf instances from an isolated scene copy; retain reusable templates.
Run on a copied project first, compare the audit and render, then promote verified outputs.
"""
import bpy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def snapshot():
    result = {}
    for obj in bpy.data.objects:
        if obj.name.startswith("Book_HX-") or any(c.name == "12 Smart books" for c in obj.users_collection):
            continue
        result[obj.name] = {
            "type": obj.type,
            "matrix": [list(row) for row in obj.matrix_world],
            "data": obj.data.name if obj.data else None,
            "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
            "vertices": len(obj.data.vertices) if obj.type == "MESH" else 0,
            "polygons": len(obj.data.polygons) if obj.type == "MESH" else 0,
        }
    return result

assert bpy.data.filepath, "Load the existing .blend first"
before = snapshot()
collection = bpy.data.collections.get("12 Smart books")
removed = len(collection.objects) if collection else 0
if collection:
    bpy.data.batch_remove(ids=list(collection.objects))
assert not any(obj.name.startswith("Book_HX-") for obj in bpy.data.objects)
assert snapshot() == before, "Unrelated geometry/materials/transforms changed"
rows = json.loads((ROOT / "public/models/book-inventory.json").read_text(encoding="utf-8"))["books"]
bpy.context.scene["smart_books_total"] = 0
bpy.context.scene["shelf_slot_capacity"] = len(rows)
# Do not rewrite external image paths when saving this isolated project copy.
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "blender/hexu-library.blend"), relative_remap=False)
audit = {"removed_objects": removed, "remaining_sample_books": 0,
         "unchanged_objects": len(before), "slot_capacity": len(rows),
         "protected_snapshot_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()}
(ROOT / "blender/empty-shelves-audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
scene = bpy.context.scene
scene.render.resolution_x = 1440
scene.render.resolution_y = 960
scene.render.resolution_percentage = 100
scene.cycles.samples = 32
scene.render.filepath = str(ROOT / "blender/library-preview.png")
bpy.ops.render.render(write_still=True)
print("EMPTY_SHELVES_VERIFIED " + json.dumps(audit), flush=True)
