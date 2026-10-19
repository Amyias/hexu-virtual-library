import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { spawnSync } from "node:child_process";

const python = [
  process.env.PYTHON,
  path.resolve(".cache/venv/Scripts/python.exe"),
  "python3",
  "python",
].find((cmd) => cmd && spawnSync(cmd, ["--version"], { windowsHide: true }).status === 0);
test(
  "desktop chrome rejects foreign documents and constrains resize bounds",
  { skip: !python },
  () => {
    const result = spawnSync(
      python,
      ["-m", "unittest", "discover", "-s", "tests", "-p", "test_window_chrome.py"],
      { encoding: "utf8", windowsHide: true, timeout: 15000 },
    );
    assert.equal(result.status, 0, result.stderr || result.error?.message);
  },
);
