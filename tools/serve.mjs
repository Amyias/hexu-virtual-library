import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const port = Number(process.env.PORT || 8080);
let libraryProcess, libraryReady;
function startBookService() {
  if (libraryReady) return libraryReady;
  libraryReady = new Promise((resolve, reject) => {
    const candidates = [
      ...(process.env.HEXU_PYTHON ? [[process.env.HEXU_PYTHON, []]] : []),
      [path.join(root, '.cache', 'venv', 'Scripts', 'python.exe'), []],
      ['py', ['-3']], ['python', []], ['python3', []],
    ];
    const found = candidates.find(([command, args]) => spawnSync(command, [...args, '-c', 'import sqlite3; print(1)'], { timeout: 3000, windowsHide: true, stdio: 'ignore' }).status === 0);
    if (!found) { reject(new Error('本地正文书库需要 Python 3；请安装 Python 或设置 HEXU_PYTHON。')); return; }
    libraryProcess = spawn(found[0], [...found[1], path.join(root, 'tools', 'library-service.py')], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    libraryProcess.stderr.resume(); // Drain server diagnostics without logging book content.
    const timer = setTimeout(() => { libraryProcess.kill(); reject(new Error('正文书库启动超时')); }, 8000);
    let output = '';
    libraryProcess.stdout.on('data', chunk => {
      output += chunk;
      if (!output.includes('\n')) return;
      try { const result = JSON.parse(output.split('\n')[0]); clearTimeout(timer); resolve(result.port); }
      catch { clearTimeout(timer); reject(new Error('正文书库启动失败')); }
    });
    libraryProcess.on('error', () => { clearTimeout(timer); reject(new Error('正文书库启动失败')); });
    libraryProcess.on('exit', () => { clearTimeout(timer); reject(new Error('正文书库已停止，请重启服务')); libraryReady = null; });
  });
  return libraryReady;
}
process.on('exit', () => libraryProcess?.kill());
process.on('SIGINT', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));
const mime = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".glb": "model/gltf-binary",
  ".png": "image/png",
};
const server = http.createServer(async (req, res) => {
  try {
    if (req.url.startsWith('/library/')) {
      try {
        const backendPort = await startBookService();
        const upstream = http.request({ hostname: '127.0.0.1', port: backendPort, path: req.url, method: req.method, headers: req.headers }, incoming => {
          res.writeHead(incoming.statusCode, incoming.headers); incoming.pipe(res);
        });
        upstream.on('error', () => { if (!res.headersSent) res.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify({ error: '正文书库连接失败，请重启服务' })); });
        req.pipe(upstream);
      } catch (error) {
        res.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify({ error: error.message }));
      }
      return;
    }
    const pathname = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
    );
    const target = path.resolve(
      root,
      "." + (pathname === "/" ? "/index.html" : pathname),
    );
    if (!target.startsWith(root + path.sep)) {
      res.writeHead(403);
      res.end();
      return;
    }
    fs.stat(target, (error, stat) => {
      if (error || !stat.isFile()) {
        res.writeHead(404);
        res.end("Not found");
        return;
      }
      res.writeHead(200, {
        "Content-Type":
          mime[path.extname(target)] || "application/octet-stream",
        "Content-Length": stat.size,
        "Cache-Control": "no-cache",
        "X-Content-Type-Options": "nosniff",
      });
      fs.createReadStream(target).pipe(res);
    });
  } catch {
    res.writeHead(400);
    res.end("Bad request");
  }
});
server.on("error", (error) => {
  console.error(
    error.code === "EADDRINUSE"
      ? `端口 ${port} 已被占用。可设置 PORT 环境变量后重试。`
      : error.message,
  );
  process.exitCode = 1;
});
server.listen(port, "127.0.0.1", () =>
  console.log(`和序 · Blender 精细模型版 http://localhost:${port}`),
);
