"""Reproduce the offline Chinese pixel font and preserve its upstream licence notices."""
import hashlib
from pathlib import Path
import urllib.request
import zipfile
import io

ROOT = Path(__file__).resolve().parents[1]
URL = "https://github.com/TakWolf/fusion-pixel-font/releases/download/2026.09.25/fusion-pixel-font-12px-monospaced-otf.woff2-v2026.09.25.zip"
SHA256 = "d55feb57eed56183d0e0b09ab04deea0cbbfece0282ba0e840e07c7feac5f812"
FILES = ["fusion-pixel-12px-monospaced-zh_hans.otf.woff2", "OFL.txt", "LICENSES/ark-pixel/OFL.txt",
         "LICENSES/cubic-11/OFL.txt", "LICENSES/galmuri/LICENSE.txt"]
with urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent":"hexu-library-font-preparation"}), timeout=40) as response:
    data = response.read()
assert hashlib.sha256(data).hexdigest() == SHA256, "Unexpected font archive"
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    assert archive.testzip() is None
    for name in FILES:
        target = ROOT / "public/fonts/fusion-pixel" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(name))
print("Pixel font and licence notices verified")
