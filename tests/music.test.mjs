import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';

function request(port, file, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port, path: file, headers, agent: false }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on('error', reject);
  });
}

const python = [process.env.PYTHON, path.resolve('.cache/venv/Scripts/python.exe'), 'python3', 'python']
  .find(cmd => cmd && spawnSync(cmd, ['--version'], { windowsHide: true }).status === 0);

for (const kind of ['node', 'python']) {
  test(`${kind} serves both provided MP3s with accurate seek ranges`, { skip: kind === 'python' && !python ? 'no Python' : false }, async t => {
    const port = 22000 + Math.floor(Math.random() * 4000);
    const server = spawn(kind === 'node' ? process.execPath : python,
      kind === 'node' ? ['tools/serve.mjs'] : ['tools/asr-server.py', '--no-browser', '--port', String(port)],
      { env: { ...process.env, PORT: String(port) }, windowsHide: true, stdio: 'ignore' });
    t.after(() => server.kill());
    let ready = false;
    for (let attempt = 0; attempt < 60; attempt++) {
      try { ready = (await request(port, '/index.html')).status === 200; } catch { /* Starting. */ }
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(ready, 'static server started');
    for (const name of ['01_Saint_Barbara_Theme.mp3', '02_The_Trek.mp3']) {
      const file = '/public/audio/' + name;
      const bytes = fs.readFileSync('.' + file);
      assert.ok(bytes.length > 1000000);
      const first = await request(port, file, { Range: 'bytes=0-31' });
      assert.equal(first.status, 206);
      assert.equal(first.headers['content-type'], 'audio/mpeg');
      assert.equal(first.headers['accept-ranges'], 'bytes');
      assert.equal(first.headers['content-range'], `bytes 0-31/${bytes.length}`);
      assert.equal(Number(first.headers['content-length']), 32);
      assert.deepEqual(first.body, bytes.subarray(0, 32));
      const tail = await request(port, file, { Range: 'bytes=-32' });
      assert.equal(tail.status, 206);
      assert.deepEqual(tail.body, bytes.subarray(-32));
      const clamp = await request(port, file, { Range: `bytes=${bytes.length - 8}-${bytes.length + 50}` });
      assert.equal(clamp.status, 206);
      assert.deepEqual(clamp.body, bytes.subarray(-8));
      for (const range of [`bytes=${bytes.length}-`, 'bytes=20-10', 'bytes=-0', 'bytes=bad']) {
        const invalid = await request(port, file, { Range: range });
        assert.equal(invalid.status, 416);
        assert.equal(invalid.headers['content-range'], `bytes */${bytes.length}`);
        assert.equal(invalid.body.length, 0);
      }
    }
  });
}
