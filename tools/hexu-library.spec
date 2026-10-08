# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the local, double-clickable build of the library.

One directory rather than one file, deliberately: a single-file build unpacks its whole archive
into a temporary directory on every launch, and with a 228 MiB speech model inside that is a wait
nobody would accept at every start. One directory unpacks nothing, so launch is instant.

The program's own name is set here rather than on the command line. This shell mangles Chinese
in argv (it converts UTF-8 to the console code page), and a file read as UTF-8 has no such
problem.

Built by tools/package-local.mjs. See DEPLOY.md, 「本机版打包」.
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

HERE = Path(SPECPATH)
MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
STAGE = HERE.parent / ".cache" / "stage" / "site"
MODEL_DIR = Path(
    os.environ.get("HEXU_ASR_MODEL_DIR") or HERE.parent / ".cache" / "models" / MODEL_NAME
)

# The site as the server expects to serve it: index.html, src/ and public/ side by side, with
# the pre-compressed .gz siblings the packaging step wrote next to them. public/textures is left
# out on purpose — every one of those textures is already embedded in hexu-library.glb, and the
# loose copies only feed Blender.
datas = [(str(STAGE), ".")]
# Only what the recogniser opens at runtime; test_wavs and the export script stay behind.
for name in ("model.int8.onnx", "tokens.txt", "LICENSE"):
    source = MODEL_DIR / name
    if not source.is_file():
        raise SystemExit(f"缺少模型文件：{source}（先运行 node tools/package-local.mjs）")
    datas.append((str(source), "models/sense-voice"))

# sherpa-onnx is a compiled extension plus its shared libraries; neither is discovered by
# static analysis of the two deferred imports inside transcribe().
binaries = collect_dynamic_libs("sherpa_onnx")
datas += collect_data_files("sherpa_onnx")
hiddenimports = ["sherpa_onnx", "numpy"]

# tkinter is never used here and drags in a tcl/tk runtime worth about ten megabytes. Nothing
# else is excluded: a missing stdlib module is an ImportError at the least convenient moment.
excludes = ["tkinter", "_tkinter", "pydoc_data"]

a = Analysis(
    [str(HERE / "asr-server.py")],
    pathex=[str(HERE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="和序图书馆",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # A console window on purpose: it prints the address, shows whether the recogniser loaded,
    # and closing it stops the program. A windowless build would leave the reader guessing.
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="和序图书馆",
)
