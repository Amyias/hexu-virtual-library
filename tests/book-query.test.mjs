import test from 'node:test';
import assert from 'node:assert/strict';
import { bookQuery } from '../src/reader/library.js';

test('spoken book requests strip commands while preserving titles and English spacing', () => {
  assert.equal(bookQuery('小和，我要找《狂人日记》'), '狂人日记');
  assert.equal(bookQuery('小荷，帮我下载红楼梦的正文'), '红楼梦');
  assert.equal(bookQuery('请找尚书'), '尚书');
  assert.equal(bookQuery('帮我找 Pride and Prejudice'), 'Pride and Prejudice');
});
