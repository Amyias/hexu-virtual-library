import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

test(
  "Windows shortcuts preserve Chinese paths and update only matching pinned icons",
  {
    skip: process.platform !== "win32",
  },
  (t) => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), "hexu-shortcut-"));
    t.after(() => {
      assert.equal(path.dirname(path.resolve(directory)), path.resolve(os.tmpdir()));
      assert.ok(path.basename(directory).startsWith("hexu-shortcut-"));
      fs.rmSync(directory, { recursive: true, force: true });
    });
    const desktop = path.join(directory, "桌面");
    const pinned = path.join(directory, "固定项");
    const app = path.join(directory, "和序图书馆");
    for (const folder of [desktop, pinned, app]) fs.mkdirSync(folder);
    const target = path.join(app, "和序图书馆.exe");
    const other = path.join(app, "其他程序.exe");
    fs.writeFileSync(target, "shortcut fixture, never executed");
    fs.writeFileSync(other, "unrelated shortcut fixture, never executed");
    const icon = path.join(app, "小和.ico");
    const previous = path.join(app, "旧图标.ico");
    for (const file of [icon, previous]) fs.copyFileSync("public/favicon.ico", file);
    function write(name, folder, executable, picture, pins) {
      const spec = path.join(directory, "spec.json");
      const report = path.join(directory, "report.json");
      fs.writeFileSync(
        spec,
        JSON.stringify({
          name,
          directory: folder,
          pinnedDirectory: pins,
          target: executable,
          workingDirectory: app,
          description: "小和图标测试",
          icon: picture,
        }),
      );
      fs.rmSync(report, { force: true });
      const result = spawnSync(
        "powershell",
        ["-NoProfile", "-NonInteractive", "-Command", "& $env:HEXU_SHORTCUT_SCRIPT"],
        {
          env: {
            ...process.env,
            HEXU_SHORTCUT_SCRIPT: path.resolve("tools/desktop-shortcut.ps1"),
            HEXU_SHORTCUT_SPEC: spec,
            HEXU_SHORTCUT_REPORT: report,
          },
          windowsHide: true,
          encoding: "utf8",
          timeout: 30000,
        },
      );
      assert.equal(result.status, 0, result.stderr || result.stdout);
      return JSON.parse(fs.readFileSync(report, "utf8").replace(/^\uFEFF/, ""));
    }
    write("图书馆", pinned, target, previous, desktop);
    write("其他程序", pinned, other, previous, desktop);
    const unrelated = path.join(pinned, "其他程序.lnk");
    const before = fs.readFileSync(unrelated);
    const result = write("和序图书馆", desktop, target, icon, pinned);
    assert.equal(result.matches, true);
    assert.equal(result.exists, true);
    assert.equal(result.target, target);
    assert.equal(result.icon, icon + ",0");
    assert.equal(result.updatedPinned, 1);
    assert.equal(result.pinnedVerified, true);
    assert.deepEqual(fs.readFileSync(unrelated), before);
  },
);
