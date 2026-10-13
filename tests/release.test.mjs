import test from 'node:test';
import assert from 'node:assert/strict';
import { matchesArchive, requireModelForSkip, requireCompleteRelease, findRelease } from '../tools/release-policy.mjs';

const hash = 'a'.repeat(64);
const asset = (name, extra = {}) => ({ name, state: 'uploaded', size: 1234, digest: `sha256:${hash}`, ...extra });
const program = asset('hexu-library-2.3.0-program.zip');
const model = asset('sense-voice-2.3.0.zip');

test('release completion rejects the program-only installation shown in the report', () => {
  assert.throws(() => requireCompleteRelease('2.3.0', { assets: [program] }), /sense-voice-2.3.0.zip/);
  assert.doesNotThrow(() => requireCompleteRelease('2.3.0', { assets: [program, model] }));
  for (const extra of [{ state: 'starter' }, { size: 0 }, { digest: null }]) {
    assert.throws(() => requireCompleteRelease('2.3.0', { assets: [program, asset(model.name, extra)] }));
  }
});

test('skipping a model requires the complete model in this release, not a historical one', () => {
  assert.throws(() => requireModelForSkip('2.3.0', null));
  assert.throws(() => requireModelForSkip('2.3.0', { tag_name: 'v2.1.1', assets: [asset('sense-voice-2.1.1.zip')] }));
  assert.throws(() => requireModelForSkip('2.3.0', { tag_name: 'v2.3.0', assets: [program] }));
  assert.doesNotThrow(() => requireModelForSkip('2.3.0', { tag_name: 'v2.3.0', assets: [model] }));
});

test('same-sized or half-uploaded archives are not accepted as verified uploads', () => {
  assert.equal(matchesArchive(model, 1234, hash), true);
  assert.equal(matchesArchive(model, 1234, 'b'.repeat(64)), false);
  assert.equal(matchesArchive({ ...model, state: 'starter' }, 1234, hash), false);
  assert.equal(matchesArchive(model, 5678, hash), false);
});

test('a draft release is found by tag in the release list, which the tag endpoint never returns', () => {
  const draft = { id: 2, tag_name: 'v2.4.1', draft: true };
  const releases = [draft, { id: 1, tag_name: 'v2.4.0', draft: false }];
  assert.equal(findRelease('2.4.1', releases), draft);
  assert.equal(findRelease('2.4.2', releases), null);
  assert.equal(findRelease('2.4.1', null), null);
});
