import test from "node:test";
import assert from "node:assert/strict";
import {
  matchesArchive,
  requireModelForSkip,
  requireCompleteRelease,
  findRelease,
  notesRange,
} from "../tools/release-policy.mjs";

const hash = "a".repeat(64);
const asset = (name, extra = {}) => ({
  name,
  state: "uploaded",
  size: 1234,
  digest: `sha256:${hash}`,
  ...extra,
});
const program = asset("hexu-library-2.3.0-program.zip");
const model = asset("sense-voice-2.3.0.zip");

test("release completion rejects the program-only installation shown in the report", () => {
  assert.throws(
    () => requireCompleteRelease("2.3.0", { assets: [program] }),
    /sense-voice-2.3.0.zip/,
  );
  assert.doesNotThrow(() => requireCompleteRelease("2.3.0", { assets: [program, model] }));
  for (const extra of [{ state: "starter" }, { size: 0 }, { digest: null }]) {
    assert.throws(() =>
      requireCompleteRelease("2.3.0", { assets: [program, asset(model.name, extra)] }),
    );
  }
});

test("skipping a model requires the complete model in this release, not a historical one", () => {
  assert.throws(() => requireModelForSkip("2.3.0", null));
  assert.throws(() =>
    requireModelForSkip("2.3.0", { tag_name: "v2.1.1", assets: [asset("sense-voice-2.1.1.zip")] }),
  );
  assert.throws(() => requireModelForSkip("2.3.0", { tag_name: "v2.3.0", assets: [program] }));
  assert.doesNotThrow(() => requireModelForSkip("2.3.0", { tag_name: "v2.3.0", assets: [model] }));
});

test("same-sized or half-uploaded archives are not accepted as verified uploads", () => {
  assert.equal(matchesArchive(model, 1234, hash), true);
  assert.equal(matchesArchive(model, 1234, "b".repeat(64)), false);
  assert.equal(matchesArchive({ ...model, state: "starter" }, 1234, hash), false);
  assert.equal(matchesArchive(model, 5678, hash), false);
});

test("a draft release is found by tag in the release list, which the tag endpoint never returns", () => {
  const draft = { id: 2, tag_name: "v2.4.1", draft: true };
  const releases = [draft, { id: 1, tag_name: "v2.4.0", draft: false }];
  assert.equal(findRelease("2.4.1", releases), draft);
  assert.equal(findRelease("2.4.2", releases), null);
  assert.equal(findRelease("2.4.1", null), null);
});

test("release notes cover the commits since the previous version, not a fixed window", async () => {
  assert.deepEqual(notesRange("v2.4.1", "abc123"), ["v2.4.1..abc123"]);
  assert.deepEqual(notesRange("", "abc123"), ["-n", "15", "abc123"]);
  // Against this repository's own history: v2.5.0 added exactly what came after v2.4.1.
  const { spawnSync } = await import("node:child_process");
  const git = (...args) => spawnSync("git", args, { encoding: "utf8" });
  if (git("rev-parse", "--verify", "--quiet", "v2.5.0^{commit}").status !== 0) return; // a clone without tags
  const previous = git(
    "describe",
    "--tags",
    "--abbrev=0",
    "--match",
    "v[0-9]*",
    "v2.5.0^",
  ).stdout.trim();
  assert.equal(previous, "v2.4.1");
  const subjects = git("log", "--pretty=format:%s", ...notesRange(previous, "v2.5.0"))
    .stdout.trim()
    .split("\n");
  assert.equal(subjects.length, 3);
  assert.ok(
    !subjects.some((s) => s.includes("2.4.1")),
    "commits of v2.4.1 itself are not repeated",
  );
});
