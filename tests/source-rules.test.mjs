import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { spawnSync } from "node:child_process";

const python = [
  process.env.PYTHON,
  path.resolve(".cache/venv/Scripts/python.exe"),
  "python3",
  "python",
].find(
  (command) =>
    command &&
    spawnSync(command, ["-c", "import quickjs, lxml.html, jsonpath_ng.ext, cssselect"], {
      windowsHide: true,
      timeout: 5000,
    }).status === 0,
);
test(
  "source rules import, JS/JSONPath/XPath download, pagination, enable state and runtime boundaries",
  {
    skip: !python && "install tools/requirements-sources.txt to test source compatibility",
  },
  () => {
    const result = spawnSync(
      python,
      ["-m", "unittest", "discover", "-s", "tests", "-p", "test_source_rules.py"],
      { encoding: "utf8", windowsHide: true, timeout: 15000 },
    );
    assert.equal(result.status, 0, result.stderr || result.error?.message);
  },
);

test(
  "semantic catalogue follows real local imports and rejects empty physical slots",
  { skip: !python },
  () => {
    const result = spawnSync(
      python,
      ["-m", "unittest", "discover", "-s", "tests", "-p", "test_shelf_catalog.py"],
      { encoding: "utf8", windowsHide: true, timeout: 15000 },
    );
    assert.equal(result.status, 0, result.stderr || result.error?.message);
  },
);

for (const filename of [
  "test_builtin_sources.py",
  "test_book_library.py",
  "test_windows_book_http.py",
]) {
  test(`book providers and library integration: ${filename}`, { skip: !python }, () => {
    const result = spawnSync(
      python,
      ["-m", "unittest", "discover", "-s", "tests", "-p", filename],
      { encoding: "utf8", windowsHide: true, timeout: 15000 },
    );
    assert.equal(result.status, 0, result.stderr || result.error?.message);
  });
}
