import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const python = [process.env.PYTHON, path.resolve('.cache/venv/Scripts/python.exe'), 'python3', 'python']
  .find(cmd => cmd && spawnSync(cmd, ['--version'], { windowsHide: true }).status === 0);

test('automatic update triggers, retries, restarts and cleans old installation', { skip: !python ? 'no Python' : false }, () => {
  const result = spawnSync(python, ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_auto_update.py'], {
    windowsHide: true, encoding: 'utf8', timeout: 120000,
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
