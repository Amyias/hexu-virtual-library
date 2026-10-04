# 开发与提交约定

本文件记录本项目的工作流约定、远端仓库信息与凭据位置。动手改代码前请先读完。

## 每次改动后：验证 → 提交 → 推送

一个「改动」指**一件完成且已验证的逻辑变更**，不是每次保存文件。流程固定三步，不需要额外确认。

### 1. 验证

- 任何改动都先跑 `npm test`。当前 6 项：馆藏几何与书架结构、`hexu-library.glb` 合并契约、`smart-book.glb` 部件命名、三份馆藏清单副本一致性、ASR 生命周期。
- 涉及界面、场景、动画或交互的改动，另外在浏览器里回归一遍完整链路：加载场景 → 找书 → 翻开封面 → 查看芯片 → 放回书架 → 回到待命。
- 改动 Blender 脚本后，**先把项目复制到临时目录跑重建**，与现有产物对比，不要直接覆盖仓库里的成品模型。

### 2. 提交

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

## 远端仓库

| 项 | 值 |
| --- | --- |
| 平台 | Gitee |
| 仓库 | `li-tao-yi/hexu-virtual-library` |
| 地址 | https://gitee.com/li-tao-yi/hexu-virtual-library |
| 可见性 | 私有 |
| 默认分支 | `master` |
| 远端 | `git@gitee.com:li-tao-yi/hexu-virtual-library.git` |

远端使用 SSH，因此**推送不需要任何令牌**。

## 凭据

**凭据值不写入任何文件。** 本仓库的源码、文档、示例与测试中只出现变量名与路径，绝不含明文令牌或私钥。

处理凭据时不可例外地遵守：

- 绝不读取、打印、回显、记录或上传凭据值；不要把它展开到命令输出、日志、临时文件、提交信息或任何对外请求里。
- 凭据只在该工具真正需要它的那一次调用中从环境变量读取，不复制、不缓存、不写入磁盘。
- 若某次输出可能包含凭据值，先遮蔽再输出。
- 不需要凭据的任务（例如日常提交推送走 SSH），不要去读取凭据。

### 推送认证：SSH 密钥

| 项 | 位置 |
| --- | --- |
| 私钥 | `~/.ssh/id_ed25519`（即 `C:\Users\<用户名>\.ssh\id_ed25519`） |
| 公钥 | `~/.ssh/id_ed25519.pub`，已登记到 Gitee 账号 |
| 验证 | `ssh -T git@gitee.com`，成功时返回 `Hi 李焘屹(@li-tao-yi)!` |

密钥位于用户目录，不在仓库内，也不会被提交。

### API 认证：Gitee 个人访问令牌

仅调用 Gitee REST API（新建仓库、修改仓库描述等）时需要；日常提交推送用不到。

| 项 | 位置 |
| --- | --- |
| 变量名 | `GITEE_ACCESS_TOKEN` |
| 存放 | Windows 环境变量，明文 `REG_SZ` |
| 用户级 | `HKCU\Environment` |
| 系统级 | `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment` |
| 所需权限 | 至少 `user_info`（读账号）与 `projects`（建仓库） |

检查是否已配置（不会打印令牌内容）：

```bash
test -n "$GITEE_ACCESS_TOKEN" && echo "已配置" || echo "未配置"
```

读取与持久化设置：

```powershell
# 查看。会显示明文值，注意不要把输出粘贴进任何文件或对话
reg query "HKCU\Environment" /v GITEE_ACCESS_TOKEN

# 持久化设置，新开终端后生效
setx GITEE_ACCESS_TOKEN "<你的令牌>"
```

> 当前令牌在用户级与系统级各有一份，系统级那份本机所有用户与进程都能读到。若只想给当前用户使用，可删除系统级那份，只保留用户级。

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

## 不应提交的内容

`.gitignore` 已排除：

| 路径 | 原因 |
| --- | --- |
| `node_modules/` | 项目无 npm 依赖，仅工具缓存 |
| `blender/__pycache__/`、`*.pyc` | Python 字节码 |
| `blender/*.blend1` | Blender 保存时自动生成的上一版备份 |
| `.mimosa/` | 本机安全扫描插件的钩子状态，与项目无关 |

`archive/` 下的 `.blend` 是**有意保留**的版本备份（植物精细化前、芯片体系前），应当提交。

`public/models/*.glb`、`blender/*.blend`、贴图与渲染图都在仓库内，这是项目的设计意图：模型与渲染依赖随项目分发，不依赖外部 CDN。

## 常用命令

```powershell
npm start                      # 本地服务，http://localhost:8080
npm test                       # 回归测试

# 全量重建模型：覆盖 .blend / .glb / 贴图 / 预览
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python-exit-code 1 --python blender/build_library.py

# 在 Blender 手动编辑并保存后，只重新导出与渲染，不重建
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup blender/hexu-library.blend --python-exit-code 1 --python blender/export_saved.py

# 重新生成馆藏清单（一次写入三份副本，必须保持一致）
node tools/prepare-smart-books.mjs

# 拉取表面贴图（幂等；--force 强制重下）
node tools/fetch-textures.mjs
```

改动馆藏坐标后，应重跑 `prepare-smart-books.mjs` 并重建模型，避免书籍与预留槽位不一致。

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
- **不放进识别适配器**。`tests/library.test.mjs` 锁定了适配器必须在 `onresult` 内**同步**派发（`deepEqual(finals, [...])` 那两条），而网络调用做不到同步。它放在 `src/app.js` 的 `processText` 这一层。
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
