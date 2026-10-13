import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";

/* 本机服务只用到标准库与同目录的 updater，不需要识别模型即可启动。
   没有 Python 的机器上跳过，而不是报错。 */
const python = [process.env.PYTHON, "python3", "python"].find(
  (cmd) => cmd && spawnSync(cmd, ["--version"]).status === 0,
);

function request(port, method, pathname, headers = {}, body) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      { host: "127.0.0.1", port, method, path: pathname, headers, agent: false },
      (res) => {
        res.resume();
        res.on("end", () => resolve(res.statusCode));
      },
    );
    req.on("error", reject);
    req.end(body);
  });
}

async function waitForServer(port) {
  for (let i = 0; i < 50; i++) {
    try {
      if ((await request(port, "GET", "/healthz")) === 200) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("asr-server did not start");
}

test("local settings refuse other sites' pages and rebound host names", { skip: !python && "no Python" }, async (t) => {
  // 设置写入临时目录，绝不碰使用者自己的 llm.env。
  const config = fs.mkdtempSync(path.join(os.tmpdir(), "hexu-settings-"));
  const port = 18000 + Math.floor(Math.random() * 2000);
  const server = spawn(python, ["tools/asr-server.py", "--no-browser", "--port", String(port)], {
    env: { ...process.env, APPDATA: config, XDG_CONFIG_HOME: config, PORT: String(port) },
    stdio: "ignore",
  });
  t.after(() => {
    server.kill();
    fs.rmSync(config, { recursive: true, force: true });
  });
  await waitForServer(port);

  const own = `127.0.0.1:${port}`;
  const json = { "Content-Type": "application/json" };
  const write = JSON.stringify({ model: "test-model" });

  // 本机、同源：设置页自己的请求照常通过。
  assert.equal(await request(port, "GET", "/settings/state"), 200);
  assert.equal(await request(port, "GET", "/settings/state", { Host: `[::1]:${port}` }), 200);
  assert.equal(
    await request(port, "POST", "/settings/key", { ...json, Origin: `http://${own}`, "Sec-Fetch-Site": "same-origin" }, write),
    200,
  );

  // 别的网页：text/plain 是无需预检的简单请求，只能靠 Origin 与 Sec-Fetch-Site 认出来。
  const plain = { "Content-Type": "text/plain" };
  assert.equal(await request(port, "POST", "/settings/key", { ...plain, Origin: "https://evil.example" }, write), 403);
  assert.equal(await request(port, "POST", "/settings/key", { ...plain, Origin: "null" }, write), 403);
  assert.equal(await request(port, "POST", "/settings/key", { ...plain, "Sec-Fetch-Site": "cross-site" }, write), 403);
  // localhost 的另一个端口算 same-site，但不是同源。
  assert.equal(await request(port, "POST", "/update/apply", { Origin: `http://localhost:${port + 1}` }), 403);
  assert.equal(await request(port, "POST", "/understand", { ...json, Origin: "https://evil.example" }, "{}"), 403);
  // 正文书库自己也查 Origin，但要先过这一道：Sec-Fetch-Site 只在这里看。
  assert.equal(await request(port, "POST", "/library/sources", { ...json, "Sec-Fetch-Site": "cross-site" }, "{}"), 403);
  assert.equal(await request(port, "GET", "/settings/state", { "Sec-Fetch-Site": "cross-site" }), 403);

  // DNS 重绑定：攻击者的域名解析到 127.0.0.1，Origin 与 Host 一致，只有主机名露馅。
  const rebound = `evil.example:${port}`;
  assert.equal(await request(port, "GET", "/settings/state", { Host: rebound }), 403);
  assert.equal(
    await request(port, "POST", "/settings/key", { ...json, Host: rebound, Origin: `http://${rebound}` }, write),
    403,
  );

  // 静态站点不受影响。
  assert.equal(await request(port, "GET", "/index.html", { Host: rebound }), 200);
});
