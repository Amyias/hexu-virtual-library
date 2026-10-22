/* Build the Windows setup program from an existing packaged build.

    node tools/build-setup.mjs        dist/和序图书馆 -> dist/release/hexu-library-<version>-setup.exe

The setup carries the whole program, models included, so a new machine needs this one file. The
two ZIP archives stay what the automatic updater downloads; the setup is for a first install.
Needs Inno Setup 6 (https://jrsoftware.org, free): found through HEXU_ISCC, the per-user install
under %LOCALAPPDATA%\Programs, Program Files, or PATH. tools/installer/hexu-library.iss is the
recipe; every path reaches it through the environment, because this shell re-encodes Chinese in
command-line arguments. */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { setupName } from "./release-policy.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP = "和序图书馆";

export function findCompiler(env = process.env) {
  const candidates = [
    env.HEXU_ISCC,
    env.LOCALAPPDATA && path.join(env.LOCALAPPDATA, "Programs", "Inno Setup 6", "ISCC.exe"),
    env["ProgramFiles(x86)"] && path.join(env["ProgramFiles(x86)"], "Inno Setup 6", "ISCC.exe"),
    env.ProgramFiles && path.join(env.ProgramFiles, "Inno Setup 6", "ISCC.exe"),
  ].filter(Boolean);
  const found = candidates.find((file) => fs.existsSync(file));
  if (found) return found;
  const onPath = spawnSync("where", ["ISCC.exe"], { encoding: "utf8" });
  return onPath.status === 0 ? onPath.stdout.split(/\r?\n/)[0].trim() : null;
}

/** Returns the setup's path, or throws with a message meant for the person running the build. */
export function buildSetup({
  version = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version,
  source = path.join(root, "dist", APP),
  output = path.join(root, "dist", "release"),
} = {}) {
  const compiler = findCompiler();
  if (!compiler)
    throw new Error(
      "找不到 Inno Setup 6 的 ISCC.exe。安装：winget install --id JRSoftware.InnoSetup -e --scope user\n" +
        "或用 HEXU_ISCC 指向它。",
    );
  const info = path.join(source, "_internal", "build-info.json");
  if (!fs.existsSync(info)) throw new Error(`先打包：${source} 里没有程序。`);
  const built = JSON.parse(fs.readFileSync(info, "utf8")).version;
  if (built !== version) throw new Error(`打包产物是 ${built}，不是 ${version}；先重新打包。`);
  for (const required of [
    path.join("_internal", "models", "sense-voice", "model.int8.onnx"),
    path.join("_internal", "models", "primetts", "primetts_v21_3voice.onnx"),
  ])
    if (!fs.existsSync(path.join(source, required)))
      throw new Error(`安装程序必须自带模型，缺少 ${required}`);

  fs.mkdirSync(output, { recursive: true });
  const target = path.join(output, setupName(version));
  fs.rmSync(target, { force: true });
  const result = spawnSync(
    compiler,
    ["/Q", path.join(root, "tools", "installer", "hexu-library.iss")],
    {
      stdio: "inherit",
      env: {
        ...process.env,
        HEXU_SETUP_VERSION: version,
        HEXU_SETUP_SOURCE: source,
        HEXU_SETUP_OUTPUT: output,
      },
    },
  );
  if (result.status !== 0 || !fs.existsSync(target))
    throw new Error(`Inno Setup 编译失败（退出码 ${result.status}）。`);
  return target;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const target = buildSetup();
    process.stdout.write(
      `安装程序  ${(fs.statSync(target).size / 1048576).toFixed(1)} MB  ${target}\n`,
    );
  } catch (error) {
    process.stderr.write(error.message + "\n");
    process.exitCode = 1;
  }
}
