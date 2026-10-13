// A release must support a fresh installation without searching older releases.
export const programName = version => `hexu-library-${version}-program.zip`;
export const modelName = version => `sense-voice-${version}.zip`;

export function usableAsset(asset) {
  return asset?.state === 'uploaded' && asset.size > 0 && /^sha256:[a-f0-9]{64}$/.test(asset.digest ?? '');
}

export function matchesArchive(asset, size, hash) {
  return usableAsset(asset) && asset.size === size && asset.digest === `sha256:${hash}`;
}

export function requireModelForSkip(version, release) {
  const model = release?.assets?.find(asset => asset.name === modelName(version));
  if (release?.tag_name !== `v${version}` || !usableAsset(model)) {
    throw new Error('--no-model 仅允许在当前发行版已有完整、带 SHA-256 的模型附件时使用；旧版本有模型不能代替当前版本。');
  }
}

export function requireCompleteRelease(version, release) {
  const missing = [programName(version), modelName(version)]
    .filter(name => !usableAsset(release?.assets?.find(asset => asset.name === name)));
  if (missing.length) throw new Error(`发行版附件不完整或未校验：${missing.join('、')}`);
}

// GET /releases/tags/{tag} never returns a draft, and this publisher always starts from one. The
// release list does include drafts for a token that can push, so a draft is found there by tag.
export function findRelease(version, releases) {
  return (Array.isArray(releases) ? releases : []).find(release => release?.tag_name === `v${version}`) ?? null;
}
