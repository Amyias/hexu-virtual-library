import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import book_library
spec = importlib.util.spec_from_file_location("shelf_server", Path(__file__).resolve().parents[1] / "tools/asr-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ShelfCatalogTests(unittest.TestCase):
    def test_empty_shelves_and_live_imports_have_identical_ids_to_the_frontend(self):
        with tempfile.TemporaryDirectory() as temp:
            library = book_library.BookLibrary(temp)
            with patch("book_library._instance", library):
                self.assertEqual(server.load_catalog(), ({}, []))
                self.assertNotIn("时间简史", server.system_prompt())
                first = library.save(book_library.import_document("import-one.txt", b"real text " * 100))
                second = library.save(book_library.import_document("import-two.txt", b"other text " * 100))
                by_id, named = server.load_catalog()
                self.assertEqual(list(by_id), ["HX-02273", "HX-02274"])
                self.assertEqual(by_id["HX-02273"]["id"], first["id"])
                self.assertEqual(by_id["HX-02274"]["id"], second["id"])
                self.assertNotIn("HX-00001", by_id)
                self.assertIn("import-one", server.system_prompt())
                self.assertIn("import-two", server.system_prompt())
                self.assertEqual(len(named), 2)


if __name__ == "__main__":
    unittest.main()
