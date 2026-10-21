# 开发与提交约定

本文件记录本项目的工作流约定、远端仓库信息与凭据位置。动手改代码前请先读完。

## 每次改动后：验证 → 提交 → 推送

一个「改动」指**一件完成且已验证的逻辑变更**，不是每次保存文件。流程固定三步，不需要额外确认。

### 1. 验证

- 任何改动都先跑 `npm test`。除图书馆核心测试外，还验证发行附件完整性、跳过模型的边界，以及同大小异内容和半成品附件不能算上传成功。馆藏清单只有一份且保持紧凑，空槽位不含预置书目，已有书库的编号与位置保持一致。本机设置与更新接口拒绝跨站与 DNS 重绑定请求，语义层超出每分钟额度回 429（`tests/server.test.mjs` 与 `tests/test_rate_limit.py`，需要 Python，没有则跳过）。
- 涉及界面、场景、动画或交互的改动，另外跑 `npm run test:ui`：用本机的 Chrome/Edge 无头跑完整链路（加载空场景 → 日月切换 → 导入真实 TXT → 按编号找书 → 翻开封面 → 正文翻页 → 查看芯片 → 放回书架 → 回到待命 → 按位置码再找一本），约 3–4 分钟，失败时在临时目录留下页面截图。它不进 `npm test`，因为要真实浏览器、也慢；不需要安装任何依赖（Node 22+）。真人语音与拖动封面它不覆盖，这几项仍要手工看一眼。
- 改动 Blender 脚本后，**先把项目复制到临时目录跑重建**，与现有产物对比，不要直接覆盖仓库里的成品模型。

### 2. 提交

提交前跑 `npm run format`。格式由 Prettier 决定（`.prettierrc.json`：双引号、行宽 100），范围是 `src` 下的 JS/CSS 与 `tests`、`tools`、`docs` 下的脚本；vendor、生成的清单与 Blender 的 Python 不在内。只改格式的提交单独提交，并把哈希追加到 `.git-blame-ignore-revs`；本机执行一次 `git config blame.ignoreRevsFile .git-blame-ignore-revs`，`git blame` 就会跳过它们。

使用 Conventional Commits 前缀 + 中文描述：

| 前缀 | 用途 |
| --- | --- |
| `feat` | 新增能力 |
| `fix` | 修复缺陷 |
| `docs` | 文档 |
| `refactor` | 重构（行为不变） |
| `chore` | 构建、依赖、杂务 |
| `test` | 测试 |

提交信息要写清**为什么**改，而不只是改了什么。一次提交只做一件事，不要把无关改动混在一起。

提交信息用 heredoc 传入，避免经过命令行参数（原因见下文「编码陷阱」）：

```bash
git commit -F - <<'MSG'
fix: 一句话说明修了什么

需要记下的背景与取舍。
MSG
```

### 3. 推送

```bash
git push origin master
```

GitHub 是唯一的权威仓库：源码、`model` 分支与发行版都在那里。只推 `master`，不改远端地址、不强推；推之前远端若有本机没有的提交，先 `git fetch origin` 再把本地提交 rebase 上去。推送走 SSH，不需要令牌。

### 4. 发行附件不是 Git 提交

`git push` 不上传被忽略的 `dist/`。每个新 GitHub Release 必须带两个独立 ZIP：`hexu-library-<版本>-program.zip` 和 `sense-voice-<版本>.zip`。即使模型未变，也要在该版本下提供模型附件，保证新机器只看当前发行页就能安装。

发布器默认生成并上传两个包，发布后核对 `uploaded` 状态、大小与 SHA-256。不能只凭附件名或相同大小跳过上传。`--no-model` 只能用于当前发行版已存在有效模型附件的补传场景；历史发行版有模型不满足这个条件。

补齐已发布版本的模型：`node tools/release.mjs --assets-only --model-only`。这个命令只生成并上传模型附件，不重建程序、不替换已发布程序包、不创建新发行版、不移动标签。需要已有打包输出的模型目录；缺失时先准备并验证模型，不能上传空包。可先加 `--prepare-only` 离线校验，令牌不会被读取。

上传后必须重新读取发行版附件清单，两个 ZIP 均完整才算完成；本次附件的远端大小及摘要要与本地一致。模型包还必须通过 ZIP CRC 和非空 ONNX/词表检查。`dist/` 与 `.cache/` 保持忽略，模型分支仍用于源模型备份，与 Release 可下载的完整模型 ZIP 用途不同。

新版本先创建草稿，两个附件全部验证后才公开发布；失败时保留草稿，之后用 `--assets-only` 补齐。修改归档器还需运行 `python -m unittest discover -s tests -p test_archive.py`，覆盖真实 ZIP 内容和缺失/空模型拒绝路径。

## 远端仓库

| 项 | 值 |
| --- | --- |
| 平台 | GitHub |
| 仓库 | `Amyias/hexu-virtual-library` |
| 地址 | https://github.com/Amyias/hexu-virtual-library |
| 可见性 | 私有 |
| 分支 | `master`（源码）、`model`（语音识别模型分块，见下文「模型在哪」） |
| 远端 | `git@github.com:Amyias/hexu-virtual-library.git`，远端名 `origin` |
| 发行版 | https://github.com/Amyias/hexu-virtual-library/releases，程序更新从这里下载 |

远端使用 SSH，因此**推送不需要任何令牌**。

> 早期的 Gitee 仓库 `li-tao-yi/hexu-virtual-library` 已停止同步并从本机远端移除，仓库描述已标注迁移、Issue 与 Pull Request 已关闭，内容停在 GitHub 之前的某个提交（`efe19c0`）。不要再从那里拉取或推送。Gitee 的「关闭仓库」状态 API 不支持，需要在网页「管理 → 仓库设置 → 仓库状态」里手动设置。

## 凭据

**凭据值不写入任何文件。** 本仓库的源码、文档、示例与测试中只出现变量名与路径，绝不含明文令牌或私钥。

处理凭据时不可例外地遵守：

- 绝不读取、打印、回显、记录或上传凭据值；不要把它展开到命令输出、日志、临时文件、提交信息或任何对外请求里。
- 凭据只在该工具真正需要它的那一次调用中从环境变量读取，不复制、不缓存、不写入磁盘。
- 若某次输出可能包含凭据值，先遮蔽再输出。
- 不需要凭据的任务（例如日常提交推送走 SSH），不要去读取凭据。

### 边界：谁在什么情况下可以写凭据

上面那条约束的是**这份仓库**，也约束**我**：文件里只许出现变量名与路径。它并不意味着使用者不能在本机保存自己的密钥——否则打包出来的本机程序每次启动都要重新输入。

所以边界划在**仓库之外、由使用者自己经手**：

| 场景 | 谁写入 | 落在哪里 | 是否属于「凭据不写入文件」的例外 |
| --- | --- | --- | --- |
| 服务器部署 | 使用者（照 `DEPLOY.md` 的命令） | `/etc/hexu-library/llm.env`，root-only 600 | 否——在仓库外，且不是我写的 |
| 本机版 | 使用者在 `/settings` 页面自己输入 | `%APPDATA%\hexu-library\llm.env` 或 `~/.config/hexu-library/llm.env` | 否——同上，由使用者触发 |
| 开发调试 | 使用者设环境变量 | 进程环境 | 否 |

三条不能松的地方：**密钥绝不写进仓库内的任何文件**；**任何 HTTP 接口都不回显密钥原文**（`/settings/state` 只回 `configured` 布尔值与来源）；**我本人不经手密钥值**——设置页那条路径由使用者自己点、程序自己存，我既不读取也不验证其内容，测试时只用明显无效的假值。

### 推送认证：SSH 密钥

| 项 | 位置 |
| --- | --- |
| 私钥 | `~/.ssh/id_ed25519`（即 `C:\Users\<用户名>\.ssh\id_ed25519`） |
| 公钥 | `~/.ssh/id_ed25519.pub`，已登记到 GitHub 账号 |
| 验证 | `ssh -T git@github.com`，成功时返回 `Hi Amyias! You've successfully authenticated…` |

密钥位于用户目录，不在仓库内，也不会被提交。

### API 认证：GitHub 个人访问令牌（发布发行版用）

仅发布 GitHub 发行版时需要；程序在别的机器上检查更新用的是同一类令牌，但**只读**即可。

| 项 | 位置 |
| --- | --- |
| 变量名 | `GITHUB_TOKEN` |
| 所需权限 | 细粒度 PAT，`Contents: Read and write`（发版）；`Contents: Read-only`（只更新） |
| 存放 | Windows 用户级环境变量（`HKCU\Environment`）；设置后新开终端生效 |

检查是否已配置（不会打印令牌内容）：`test -n "$GITHUB_TOKEN" && echo 已配置 || echo 未配置`

### 不再需要：Gitee 个人访问令牌

仓库迁到 GitHub 后，`GITEE_ACCESS_TOKEN` 已没有任何工具使用。本机若仍设着它（用户级与系统级各一份），可以删掉——系统级那份本机所有用户与进程都能读到。

## 编码陷阱：命令行不要传中文

Git Bash 会把命令行参数里的 UTF-8 中文转成 GBK 字节再交给程序。**建库时仓库描述就是这样损坏的**——服务端收到 64 个 `U+FFFD` 替换字符。

传给外部程序非 ASCII 内容时，一律改为文件传参：

```bash
# 错误：中文经 argv 传递会被破坏
curl -X PATCH "$API" -d "description=中文描述"

# 正确：内容先写入 UTF-8 文件，由程序读取
curl -X PATCH "$API" --data-urlencode "description@/path/to/desc.txt"
```

`git commit -F -` 配合 heredoc 是安全的（heredoc 不经过 argv），提交信息不会损坏。

### 同类的第二个坑：PowerShell 按 ANSI 解码

Windows PowerShell 5.1 用**控制台代码页**（本机是 GBK）解码两样东西：无 BOM 的 `.ps1` 文件、以及 `-Command` 参数里的非 ASCII。用 UTF-8 写一个含中文的 `.ps1`，里面的中文字符串到达脚本时就已经是乱码，而且**不报错**。

还有一层更容易误判：PowerShell 把中文写到 stdout 时用的是 GBK，Node/Python 按 UTF-8 读就成了 `锟斤拷`（U+FFFD）。**那只是显示坏了，文件可能是好的**——`tools/package-local.mjs` 建桌面快捷方式时就是这样，一度看起来像把文件名写坏了，其实 `.lnk` 完全正确。判断这类问题要看磁盘上的真实字节，别信控制台。

可靠做法（`desktopShortcut()` 用的就是它）：脚本正文保持纯 ASCII，中文值写进一个 UTF-8 文件，脚本用 `Get-Content -Encoding UTF8` 读；需要回传结果时同样写文件，不要走 stdout。

## 模型在哪

语音识别模型（228 MiB）**在 `model` 分支上**，不在 `master`：GitHub 单文件上限 100 MiB 装不下，
所以切成 3 块（`model/README.md` 有完整说明）。

`master` 一切照旧：`model/` 已加进 `.gitignore`，防止工作区里的副本被误提交。打包时若本地没有
模型，`tools/package-local.mjs` 会用 `git show model:model/...` 从分支取回（不动索引与工作区）、
校验 SHA-256、拼回 `.cache/models/`。

## 不应提交的内容

`.gitignore` 已排除：

| 路径 | 原因 |
| --- | --- |
| `node_modules/` | 项目无 npm 依赖，仅工具缓存 |
| `blender/__pycache__/`、`*.pyc` | Python 字节码 |
| `blender/*.blend1` | Blender 保存时自动生成的上一版备份 |
| `.mimosa/` | 本机安全扫描插件的钩子状态，与项目无关 |
| `.cache/` | 本机版打包的中间物：构建用虚拟环境、228 MiB 识别模型、PyInstaller 工作目录 |
| `dist/` | 本机版的发行产物（约 400 MB），由 `tools/package-local.mjs` 随时重建 |

前两项由 `tools/package-local.mjs` 生成，不进版本库；进版本库的是**打包脚本、spec 与文档**，所以换一台机器也能重建出同样的程序。

`archive/` 下的 `.blend` 是**有意保留**的版本备份（植物精细化前、芯片体系前），应当提交。

`public/models/*.glb`、`blender/*.blend`、贴图与渲染图都在仓库内，这是项目的设计意图：模型与渲染依赖随项目分发，不依赖外部 CDN。

## 常用命令

```powershell
npm start                      # 本地服务，http://localhost:8080
npm test                       # 回归测试
npm run format                 # 统一 JS/CSS 格式（Prettier，经 npx 运行，不需要 npm install）
npm run format:check           # 只检查，不改文件

# 本机版：打包成双击可运行的程序（自带识别模型），产物在 dist/和序图书馆/
node tools/package-local.mjs           # 或 npm run package:local
node tools/package-local.mjs --zip     # 另出一个 zip
node tools/package-local.mjs --no-build --shortcut   # 只放桌面快捷方式，不重打包

# 本机版：从源码直接跑窗口模式（默认是浏览器，--window 才是内嵌窗口）
.cache/venv/Scripts/python.exe tools/asr-server.py --window
# 检查内嵌窗口里的麦克风能不能用（结论也写进 %APPDATA%\hexu-library\mic-check.txt）
.cache/venv/Scripts/python.exe tools/asr-server.py --check-mic
# 发布一个版本（先在 package.json 改版本号并提交；没有令牌时加 --prepare-only 只备包）
node tools/release.mjs

# 检查有没有新版本（0 已最新 / 1 有更新 / 2 查不了）
.cache/venv/Scripts/python.exe tools/asr-server.py --check-update

# 重新生成程序图标（页面标签、窗口、exe、桌面快捷方式共用 public/favicon.ico）
python tools/make-icon.py

# 全量重建模型：覆盖 .blend / .glb / 贴图 / 预览
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python-exit-code 1 --python blender/build_library.py

# 在 Blender 手动编辑并保存后，只重新导出与渲染，不重建
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup blender/hexu-library.blend --python-exit-code 1 --python blender/export_saved.py

# 重新生成馆藏清单（只写 public/models/book-inventory.json 一份）
node tools/prepare-smart-books.mjs

# 按清单重建源头 .blend 里的书（只重建书，不动环境几何；注意要带上 .blend 参数，
# 漏掉它会以空场景启动，脚本照样成功但会把环境清空）
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup blender/hexu-library.blend --python-exit-code 1 --python blender/refine_books.py

# 拉取表面贴图（幂等；--force 强制重下）
node tools/fetch-textures.mjs
```

改动馆藏坐标后，按「先清单、后模型」的顺序重跑 `prepare-smart-books.mjs` 与 `refine_books.py`，网页实例与 `.blend` 里的书才会落在同一批坐标上。

## 模型精细化的做法

Blender 位于 `D:\Blender Foundation\Blender 5.2\blender.exe`。

需要精细化某个部件时，按 `blender/BOTANICAL_REFERENCES.md` 立下的流程走：

1. **先取证**。写一个只读脚本渲染现状（加载 `.blend`、只渲染、绝不保存），确认目标部件当前粗糙在哪里。不要凭印象动手。
2. **找参考**。上网查阅该物件的形态资料，提取比例与构造要点。参考**照片**只用于观察，不下载使用。**表面贴图可以取用 CC0 素材库**（见下条），但项目专有的细节纹理（例如叶脉）仍由脚本生成。
3. **写生成模块**。新建 `blender/<部件>.py`，与 `vegetation.py` 同构：按剖面与参数程序化生成，可重复执行，自带固定随机种子。
4. **写定点替换脚本**。新建 `blender/refine_<部件>.py`，与 `refine_vegetation.py` 同构：先对无关对象取 `matrix_world` 不变量快照，替换后断言其余对象未变，再保存、导出、渲染近景。
5. **写参考文档**。新建 `blender/<部件>_REFERENCES.md`，记录参考来源、形态提取要点、生成参数与单独更新命令。
6. **验证**。`npm test`；确认面数与体积仍落在合理区间；浏览器回归一遍；与替换前的渲染对比。
7. **同步**。更新 `README.md` 的文件清单与模型统计数字。

第 4 步的不变量断言是这套流程的核心保障——它能在替换过程中**证明**只改了目标对象。跳过它就可能悄悄破坏其他已验证的模型。

不要直接把 `.blend` 或 `.glb` 覆盖了再检查。要先用副本验证，确认无误再落到仓库产物上。

### 表面贴图：CC0 素材库可以取用

地板与书柜的贴图取自 [Poly Haven](https://polyhaven.com)（**CC0**，公有领域，可自由分发），由 `tools/fetch-textures.mjs` 拉取并提交入库。

取用规则：

- **只用 CC0 或等价的自由许可**，并记录素材标识与来源。当前清单在 `tools/fetch-textures.mjs` 的 `SETS`，说明见 `blender/MATERIAL_REFERENCES.md`。
- **必须由脚本拉取**，不手工下载后丢进目录；这样来源可复核、可重建。下载脚本要求幂等。
- **素材名与文件名解耦**：输出名描述用途（`floor-oak-albedo.jpg`），不跟着素材名走，换源不会让模型已引用的文件名失效。
- **项目专有的纹理仍由脚本生成**（如 `vegetation.py` 里的叶脉图）：它们是这个场景独有的，素材库里不存在。
- 贴图是**随项目分发的资产**，与 `.glb`、`.blend` 同等待遇，需要提交。

这套规则取代了此前"不下载任何第三方贴图"的绝对说法。叶脉纹理仍由脚本生成，但那是出于必要，不再是全局禁令。

## 语音与语义：三层，先分清再动手

同一句「没反应」有三个互不相同的成因，改之前先分清，否则会修错地方。

| 现象 | 所在层 | 现有对策 |
| --- | --- | --- |
| 听到的原文是对的，但提示未匹配馆藏 | 匹配层（`src/voice/intent.js`） | 分级匹配：精确 / 片段 / 单字近似，另有可选的语义层兜底 |
| 听到的原文本身就是错词或同音字 | 识别层（浏览器 Web Speech / 服务端 SenseVoice） | 提高候选数并用候选救场；识别错得太远就无解 |
| 原文对、规则也确实匹配不了（「霍金写的那本」） | 语义层（可选，`POST /understand`） | 交给大语言模型判断要哪一本；未配置则维持原有的「暂未匹配」提示 |

**语义层的三条设计边界**（改它之前先读）：

- **本地规则优先**：规则能精确命中的不会绕这一趟，所以常见说法仍是瞬时的，模型只覆盖长尾。
- **不放进识别适配器**。`tests/library.test.mjs` 锁定了适配器必须在 `onresult` 内**同步**派发（`deepEqual(finals, [...])` 那两条），而网络调用做不到同步。它放在 `src/app/assistant.js` 的 `processText` 这一层。
- **绝不信任模型给出的目标对象**。返回的 `bookId` 一律在服务端核对是否存在于馆藏清单，编造的编号判为 `none`。`navigate` 需要书目对象上的 `origin`/`instanceIndex`，一个凭空的对象会让它崩。

配置、模型代际的坑（`thinking` 默认开启、思考模式下 `temperature` 失效）、费用与隐私，见 [DEPLOY.md](./DEPLOY.md) 的「可选的语义解析层」。

帮助面板底部的「最近识别记录」与 `window.libraryDebug.getState().recent` 会同时留下「听到的」与「实际采用的」，用来看清是哪一层出问题。改识别相关代码前先看它，不要靠猜。

匹配层的两条边界是刻意的，不要随手放宽：

- **单字查询不做近似匹配**，否则「三」之类的输入会撞上任意一本书。
- **二字书名只做精确匹配**。编辑距离分不出同音与不同音——「题」「体」同音而「国」「体」不同音，距离都是 1——放开「三体」会让「身体」「全体」「团体」「三国」「三千」全部误命中（实测 12 个常见二字词命中 8 个）。二字书名的错字交由识别器候选列表救回。

`tests/library.test.mjs` 里有一项测试专门锁住这些误命中防线，放宽阈值会直接失败。

### 若识别层确实是主要瓶颈

实测确认过：浏览器自带的 Web Speech API **硬绑定到浏览器厂商的云服务，端点不可自定义**。在连不上该服务的网络里，识别器会启动、界面显示「监听中」，然后一个结果都不返回——这一点已用本机浏览器复现，界面现在也会如实报出来（见上一节）。

**这条路已经实现**：服务器模式。浏览器录音，交给服务器上的本地模型（SenseVoice / sherpa-onnx）识别，走 SSH 隧道访问。语音不再依赖任何云服务、不需要密钥、不按量计费。部署与验证见 [DEPLOY.md](./DEPLOY.md)。

前端在启动时探测 `/asr/ready`：就绪则用服务端通道，否则完全退回 Web Speech。**静态模式因此一字未变**——`npm start` 的本地开发、既有测试路径都照旧。

其余路线（备查）：

| 路线 | 精度 | 代价 |
| --- | --- | --- |
| 服务器本地模型（**已实现**） | 好，中英日韩粤 | 需一台能连的服务器与 Python 环境；段式识别没有 interim，唤醒晚到句尾 |
| 阿里云智能语音交互（实时） | 中文与热词最好 | 需在服务端加取令牌接口，密钥只从环境变量读；按量计费；音频发给阿里云 |
| 本地 Whisper | 高，音频不出本机 | 非流式，同样失去「话说到一半就亮起」；需数百 MB 模型 |
| 浏览器内 WASM | 中等 | 保持纯静态离线，但模型要纳入分发，而仓库当前总共只有 34 MiB |

无论走哪条，都要保住 `src/voice/speech.js` 现有的对外契约：`createSpeech({ $, notice, wake, processText, getPhase })` 返回 `{ getState, stop }`，`processText` 保持三参数签名（有测试锁定），渲染层不直接接触识别器。

## 已知的脚本间隐式耦合

`export_saved.py` 通过 `exec` 复用 `build_library.py` 中「`# Merge by collection`」之后的合并段，`refine_books.py` 与 `refine_vegetation.py` 又 `exec` 了 `export_saved.py`。三者共享同一个全局命名空间，`static_books` 等变量正是靠这个机制在脚本间传递。

改动这段管线时注意：**在 `build_library.py` 里把这类变量写成字面量，会切断 `export_saved.py` 的赋值通路**。

安全扫描工具会把这几处 `exec` 报为「代码注入」。经核查不构成注入漏洞——没有任何不可信输入进入 `exec`，被执行的本来就是仓库内自行维护的文件。但这是真实的**可维护性缺陷**，重构时应改为显式函数调用。目前保持原样，以免影响已验证的导出结果。
