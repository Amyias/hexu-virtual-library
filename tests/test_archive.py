"""Exercise the actual ZIP writer used for release assets, including missing-model failures."""
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

WRITER = pathlib.Path(__file__).resolve().parents[1] / "tools" / "make-archive.py"


class ReleaseArchiveTests(unittest.TestCase):
    def write(self, source, output):
        return subprocess.run(
            [sys.executable, str(WRITER), str(output), str(source), "_internal/models", "--store",
             "--require", "_internal/models/sense-voice/model.int8.onnx",
             "--require", "_internal/models/sense-voice/tokens.txt"],
            capture_output=True,
        )

    def test_model_archive_preserves_install_paths_and_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            source = pathlib.Path(temp) / "source"
            model = source / "_internal/models/sense-voice"
            model.mkdir(parents=True)
            (model / "model.int8.onnx").write_bytes(b"test weights")
            (model / "tokens.txt").write_bytes(b"a 1\nb 2\n")
            output = pathlib.Path(temp) / "model.zip"
            result = self.write(source, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read("_internal/models/sense-voice/model.int8.onnx"), b"test weights")
                self.assertEqual(len(archive.namelist()), 2)

    def test_missing_or_empty_model_files_fail_even_with_valid_zip_crc(self):
        for empty_file in [None, "model.int8.onnx", "tokens.txt"]:
            with self.subTest(empty_file=empty_file), tempfile.TemporaryDirectory() as temp:
                source = pathlib.Path(temp) / "source"
                model = source / "_internal/models/sense-voice"
                model.mkdir(parents=True)
                if empty_file:
                    for name in ["model.int8.onnx", "tokens.txt"]:
                        (model / name).write_bytes(b"" if name == empty_file else b"content")
                result = self.write(source, pathlib.Path(temp) / "model.zip")
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
