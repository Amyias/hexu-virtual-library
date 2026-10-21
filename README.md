# 和序 · 虚拟智能图书馆

完整技术说明、SVG 系统架构图、语音流程、资产管线及扩展建议，见 [技术实现与系统架构](docs/TECHNICAL_GUIDE.md)。

跨目录或电脑分享时，使用 [完整文档包](docs/TECHNICAL_GUIDE_PORTABLE.zip)，或直接复制 [独立 HTML 文档](docs/portable/TECHNICAL_GUIDE.html)（图与样式内嵌，可离线阅读）。

Blender 精细环境模型 + Three.js 网页交互。此版本已从单文件拆分为 ES Modules，模型、贴图及渲染依赖均保存在项目中。

灯光采用窗侧日光、八盏真实位置的暖色吊灯和两盏阅读灯，配合实时软阴影与 Blender 烘焙的地面接触遮蔽。实现为 `src/scene/lighting.js`，共用灯位配置 `public/models/lighting-rig.json`，离线烘焙脚本 `blender/bake_lighting.py`；验证与参考见 [灯光说明](blender/LIGHTING_REFERENCES.md)。新增 2048×2048 AO 贴图，原 .blend、GLB、馆藏位置及模型面数均未更改。

左后方第二扇拱窗外挂着 Blender 生成的像素太阳，方位与窗侧日光一致，所以地上的影子正好背离它。右下角的「☾ / ☀」按钮切换到像素月亮：月亮占用同一位置，光源方向不变，只把日光换成冷色月光、背景转为夜蓝，并调亮吊灯与阅读灯。日月跟随系统时间自动切换（08:00–17:00 太阳，其余时间月亮）；按钮可临时手动切换，到下一个 08:00 或 17:00 自动恢复。两个天体共 4 个网格、1,436 个三角面，GLB 约 52 KiB，实现为 `blender/celestial.py`、`blender/build_celestial.py` 与 `src/scene/sky.js`，参考与重建见 [日月说明](blender/CELESTIAL_REFERENCES.md)。

## 运行

### 方式一：双击程序（推荐，含语音识别）

```
node tools/package-local.mjs      # 打包一次，产物在 dist/和序图书馆/
```

双击 `dist/和序图书馆/和序图书馆.exe`，程序**直接打开自己的窗口**，图书馆就在窗口里——没有浏览器标签页，也没有命令行黑框；关掉窗口程序即退出。用的是 Windows 自带的 WebView2（随 Edge 安装），页面、识别模型与 HTTP 服务都在本机。**识别完全在本机运行，录音不出这台电脑**，也不需要那台香港服务器。约 327 MB，构建与窗口细节见 [DEPLOY.md](./DEPLOY.md) 的「本机版打包」。

麦克风不需要你在窗口里点「允许」：程序替这个页面放行了（WebView2 默认会拒绝麦克风，所以这一步由程序完成，见 `tools/window_host.py`）。真正的开关在页面里——第一次点一下「启动语音感知」，之后每次打开都会自动开始收听，说「小和」即可。想确认窗口里麦克风能不能用，跑 `和序图书馆.exe --check-mic`；想改用系统浏览器，跑 `--browser`。

**更新**：程序启动后及运行中每 5 分钟检查 **GitHub 发行版**，发现新版后自动下载、校验、安装并重启，无需点击更新；成功后清理旧程序副本。每个发行版同时提供程序包（v2.3.0 约 48.8 MiB）与独立模型包（约 228.5 MiB）：新机器下载两个包并解压到同一目录，已有模型的机器只下载程序包。仓库私有，安装端更新需要只读令牌，可配置环境变量 `GITHUB_TOKEN` 或在设置页填写。发布时即使模型未变也必须上传当前版本的模型附件，并验证大小、状态与 SHA-256；源码推送不会自动上传这些 ZIP。细节见 [DEPLOY.md](./DEPLOY.md) 的「更新」。

大模型对话（可选）在「和 · 对话 → 模型设置」填写自己的 API 密钥、接入地址与模型名称；配置后支持自由问答、多轮追问与自然语言找书。不填仍可操作真实书架与正文书库。密钥存在用户目录，不在程序文件夹里。

### 方式二：开发服务（场景 + 本地正文书库）

已安装 Node.js 18 或更高版本时，在项目目录执行：

```powershell
npm start
```

打开 `http://localhost:8080`。不需要 `npm install`。不能直接双击 `index.html`：浏览器模块与 GLB 资源需要通过 HTTP 服务加载。正文书库需要 Python 3.10+，先运行 `python -m pip install -r tools/requirements-sources.txt` 安装内置书源解析依赖；服务会自动寻找解释器；也可设置 `HEXU_PYTHON` 指向 Python。这条运行方式没有本机识别模型，识别会退回浏览器自带的 Web Speech API（在连不上厂商云服务的网络里不可用）。

首次点击“启动语音感知”并允许麦克风，然后说“小和”或“小和，帮我找三体”。**这一次点击只需一次**：选择会被记住，此后每次打开页面都自动开始收听，直接说「小和」即可。之所以不能做到零点击，是因为浏览器的麦克风授权本身必须由用户手势触发——没有任何网页能绕过这一点；而授权一旦持久化，页面就能在无手势的新文档里自行开麦（已实测）。

支持同音词、多轮承接、自动重连和关闭监听。Web Speech API 的实际可用性取决于浏览器、权限与语音服务网络；3D 场景及本地文字找书不依赖外部 CDN。语音播报可通过 ♪ 开启。

**识别走哪条通道是自动的**：页面启动时探测 `/asr/ready`，若服务器部署了本地识别模型（见 [DEPLOY.md](./DEPLOY.md)）就用它，否则用浏览器自带的 Web Speech API。之所以需要服务端这条，是因为 Web Speech API 硬绑定到浏览器厂商的云服务、端点不可自定义——在连不上该服务的网络里它只报一个网络错误，永远不返回结果。服务端模式不需要密钥、不按量计费，代价是段式识别没有中间结果，唤醒词晚到句尾。

书名匹配带容错：三字以上的书名差一个字（「时间减史」→《时间简史》）或只说其中一段（「计算机」→《计算机基础》）都能命中，识别器返回的多个候选会一并参与匹配。二字书名只做精确匹配——编辑距离分不出同音与不同音，放开会让「身体」「三国」「沙发」这类常用词误命中，因此「三题」这类错字交由候选列表救回。调试时可通过 `window.libraryDebug.getState().recent` 查看听到的原文、实际采用的候选与是否命中，用来分辨是识别错了还是没匹配上。

**说不出书名也能找。** 服务器若配置了大语言模型（见 [DEPLOY.md](./DEPLOY.md) 的「可选的语义解析层」），规则读不懂的说法——「霍金写的那本」「讲宇宙起源最著名的那本书」——会交给模型判断要哪一本。规则能精确命中的不绕这一趟，所以常见说法仍是即时的；模型不可用时功能不退化，只是少了理解长尾的能力。阅读时还可以用嘴操作：翻开、合上、看看芯片、放回书架。

## 小说正文与本地书库

手动「下载并上架」会在持久化槽位新增一本实体书，自动近看并框出书脊，书留在架上；正文书库显示架号、面、层、顺序和芯片编号，支持「定位书架」与「从书架取阅」。旧书籍也可定位查看，重启保持原位；语音明确找书时保留自动下载后取阅的流程。

说「小和，帮我找狂人日记」：已入库则直接从书架取阅，未入库则检索真实正文；精确结果唯一时自动下载，多个候选时选择一个来源。下载完整后保存到本机并绑定空闲书架槽位，翻开封面即可逐页阅读，支持目录、字号与阅读进度恢复。点击「正文书库」也可搜索、导入 TXT / EPUB、导入 CSS / XPath / JSONPath / 纯 JS 书源 JSON。未入库的位置保持空置；不会预装演示书或编号填充书。

书库默认保存在 `%APPDATA%\hexu-library\books`，包含 SQLite 与 UTF-8 正文，程序更新不会覆盖。默认在线检索无忧书城公开目录与天涯书库；书包网（简体）保留为下拉框单独可选源，不再参加默认搜索。无忧书城通过公开 sitemap、书名拼音和实际目录元数据检索，不提交需要验证的搜索表单；多音字或特殊标题可能需要完整书名或拼音，未命中不代表站点没有该书。候选可逐章下载；同时保留书源导入与 TXT / EPUB 导入。运行方式、兼容范围与备份方法见 [正文书库使用说明](docs/BOOK_LIBRARY.md)。

**阅读音乐**：翻开 3D 封面或进入本地正文时，迷你播放器自动播放提供的《Saint Barbara Theme》《The Trek》，两首按顺序循环；支持暂停/继续、上一首/下一首、进度拖动和音量记忆。返回 3D 书本或查看芯片时保持播放，放回书架时立即停止并归零。若浏览器阻止自动播放，点击播放器的 ▶ 即可。悬浮播放器与阅读条共用液态玻璃材质：圆角距离场生成 SVG 背景折射贴图，叠加轻微色散、边缘反光及指针高光，正文和控件不参与扭曲；尺寸变化时才重算贴图，支持窄屏与减少动态效果。技术参考 [Shu Ding / liquid-glass](https://github.com/shuding/liquid-glass)，MIT 许可随源码与本机包保存于 `src/reader/LIQUID_GLASS_LICENSE.txt`。音频位于 `public/audio/`，本机打包也会携带，无需访问 Steam 目录；旧 EXE 需重新打包才会包含此功能。

## 文件结构

| 路径 | 职责 |
| --- | --- |
| `DEVELOPMENT.md` | 开发与提交约定、远端仓库与凭据位置，动手前先读 |
| `AGENTS.md` | 约定要点，供自动化代理读取 |
| `.prettierrc.json`、`.git-blame-ignore-revs` | 代码格式规则（`npm run format`）；纯格式化提交的清单，供 `git blame` 跳过 |
| `DEPLOY.md` | 服务器部署与服务端语音识别 |
| `index.html` | 页面结构、import map、本地依赖入口 |
| `src/main.js` | 启动与资源加载错误提示 |
| `src/app.js` | 启动与装配：加载场景，把下面各模块接起来，逐帧渲染 |
| `src/app/phases.js` | 显式状态机：`IDLE → NAVIGATING → PRESENTING → READING → RETURNING → IDLE`，越序请求一律拒绝 |
| `src/app/dialogue.js` | 一句话要做什么（唤醒、阅读指令、取书、交给模型或正文检索），纯函数，不碰场景 |
| `src/app/assistant.js` | 小和：执行 `dialogue.js` 的判断，所有文本输入的唯一入口 `processText` |
| `src/app/journey.js` | 取书与归还的动画编排，并在每段之间推进状态 |
| `src/app/reader-view.js` | 手中的书：封面开合、拖动、芯片特写 |
| `src/app/input.js` | 指针、滚轮、键盘与按钮绑定 |
| `src/app/feedback.js`、`src/app/motion.js` | 提示 / 气泡 / 语音播报；补间动画与取书路线 |
| `src/reader/music.js` | 阅读音乐、循环切歌、暂停、进度及音量；放回书籍时停止 |
| `public/audio/` | 用户提供的两首 MP3，随站点和本机程序携带 |
| `src/data/catalog.js` | 馆藏入口：以 JSON 模块导入 `book-inventory.json`，展开成 11360 个空槽位，书目来自本地正文库 |
| `src/data/inventory.js` | 紧凑清单的展开规则：编号、位置码、检索关键词、芯片载荷都由行号与坐标推出 |
| `src/voice/intent.js` | 唤醒词与馆藏匹配 |
| `src/voice/speech.js` | Web Speech API 生命周期和识别事件 |
| `src/voice/server-asr.js` | 服务端识别通道：录音、能量断句、上传（后端可用时才启用） |
| `src/voice/understand.js` | 语义解析通道：本地规则读不懂的说法交给大语言模型（已配置时才启用） |
| `src/scene/runtime.js` | 相机、光照、阴影、环境反射 |
| `src/scene/environment.js` | 加载 Blender GLB、悬浮分类标识、书架实例化入口 |
| `src/scene/smart-books.js` | 真实书籍的书脊实例化，未入库槽位不显示：逐实例着色与三向缩放 |
| `src/scene/companion.js` | Blender 像素宠物加载、呼吸眨眼、抬手唤醒与带路动画 |
| `src/reader/book.js` | 绕书脊铰链开合、封面与中文简介纹理、芯片特写模型 |
| `src/reader/library.js` | 正文书库面板、在线检索与下载、TXT/EPUB 和书源导入、书架位置绑定 |
| `src/reader/novel.js` | 正文测量分页、章节目录、字号与阅读进度恢复 |
| `tools/book_library.py` | SQLite 书库、UTF-8 正文、异步下载任务、导入与 HTTP API |
| `tools/book_sources.py` | 多格式书源下载管线与历史维基文库兼容适配 |
| `tools/builtin_book_sources.py` | 天涯书库 POST 搜索、书包网搜索与完整目录下载 |
| `tools/wyshu_source.py` | 无忧书城公开目录检索、书名拼音候选与真实元数据核对 |
| `tools/windows_book_http.py` | 内置书源连接异常时的 Windows 系统 HTTPS／IPv4 有界重试 |
| `tools/source_rules.py` | CSS、XPath、JSONPath 与受限 QuickJS 规则解析 |
| `tools/library-service.py` | 开发服务使用的 Python 书库子进程 |
| `docs/BOOK_LIBRARY.md` | 正文书库、书源格式与接口说明 |
| `src/styles/library.css` | 页面与响应式布局 |
| `blender/hexu-library.blend` | 可直接在 Blender 编辑的源场景 |
| `blender/build_library.py` | 可重复执行的建模、导出、渲染脚本 |
| `blender/export_saved.py` | 从已保存的源模型重新导出，不重建或覆盖源文件 |
| `blender/smart_books.py` | 硬皮书模板（下凹芯片槽）建模、`smart-book.glb` 导出、架上书实例化 |
| `blender/shelf_books.py` | 书架轻模板建模：书脊 + 书口顶边、布料与烫金纹理，导出 `shelf-book.glb` |
| `src/data/shelf-slots.js` | 空槽位分配与旧版书库位置兼容，保留已入库书籍的芯片与坐标 |
| `blender/clear_sample_books.py` | 定点清除源场景样书，断言无关对象不变 |
| `blender/refine_books.py` | 定点更新书籍，备份、导出并渲染书本、芯片与书架内景 |
| `blender/vegetation.py` | 盆栽曲面叶片、叶脉、陶盆与灌木分枝建模 |
| `blender/refine_vegetation.py` | 定点更新植物，核验其余模型不变，导出并渲染近景 |
| `blender/BOTANICAL_REFERENCES.md` | 植物形态参考、生成参数与更新方法 |
| `blender/SHELVING_REFERENCES.md` | 书架进深标准、图书摆放方式与更新方法 |
| `blender/MATERIAL_REFERENCES.md` | 地板与书柜的材质来源、UV 尺度与更新方法 |
| `blender/PENDANT_REFERENCES.md` | 吊灯的型材构造、配色与素材库结论 |
| `blender/library-preview.png` | Blender 实际渲染的场景预览 |
| `blender/celestial.py`、`blender/build_celestial.py` | 像素太阳与月亮的生成模块和独立构建脚本（带不变量快照） |
| `blender/celestial.blend`、`blender/celestial-sun.png`、`blender/celestial-moon.png` | 日月的可编辑源文件与 Blender 渲染预览；参数见 `blender/CELESTIAL_REFERENCES.md` |
| `blender/smart-book-detail.png` | 书本与芯片槽近景渲染 |
| `blender/chip-detail.png` | 芯片微刻字近景渲染 |
| `blender/shelf-detail.png` | 书架内景：书立在层板上、靠住背板 |
| `model/`（在 `model` 分支，不在 master） | 语音识别模型：228 MiB 超过 GitHub 单文件 100 MiB，切成 3 块；打包脚本自动取回并校验 |
| `public/models/hexu-library.glb` | 网页使用的合并材质环境模型（不含架上藏书） |
| `public/models/smart-book.glb` | 阅读器用的硬皮书模板（含芯片槽与铰链） |
| `public/models/shelf-book.glb` | 架上书脊模板：书脊 + 书口顶边，2 个部件、216 个三角面 |
| `public/models/celestial.glb` | 像素太阳与月亮：4 个网格、1,436 个三角面，无纹理 |
| `public/models/book-inventory.json` | 唯一一份馆藏清单（生成物，约 0.5 MB）：每个空槽位一行 `[架, 面, 层, 槽, 布色, x, y, z]`，不含预置书目；网页、测试、本机服务与 Blender 都读它 |
| `public/models/manifest.json` | 导出版本、书架规格、面数、文件大小 |
| `public/textures/floor-oak-*.jpg` | 地板贴图（反照率 / 法线 / 粗糙度），CC0 扫描件 |
| `public/textures/joinery-oak-*.jpg` | 书柜与木作贴图（同上） |
| `public/textures/botanical-leaf.png` | Blender 生成的叶片贴图，同时内嵌于 GLB |
| `public/vendor/` | Three.js 0.160.1、GLTFLoader、DRACOLoader、GSAP 3.12.5 等固定依赖 |
| `public/vendor/draco/` | Draco 解码器（Apache-2.0），环境模型用它解压几何 |
| `tools/serve.mjs` | Node 本地服务与按需启动的 Python 正文书库代理 |
| `tools/asr-server.py` | 一个进程两种跑法：服务器模式（静态站点 + 本机模型识别），或经 PyInstaller 冻结成本机程序 |
| `tools/window_host.py` | 打包版的窗口：用 WebView2 承载页面，并替页面放行麦克风（WebView2 默认拒绝） |
| `tools/updater.py` | 更新：查 GitHub 最新发行版、下载并校验程序包（断点续传）、退出后替换并重开；模型不变时不重下 |
| `tools/package-local.mjs` | 本机版打包：准备虚拟环境、校验模型、暂存站点并预压缩、调 PyInstaller、可选桌面快捷方式 |
| `tools/hexu-library.spec` | PyInstaller 配方（one-dir，程序名与数据文件清单） |
| `public/settings.html` | 本机设置页：填写模型密钥、测试连接、检查与执行更新（仅回环可访问） |
| `public/favicon.ico` | 程序图标（多尺寸）：页面标签、程序窗口、exe 与桌面快捷方式共用同一个文件 |
| `tools/make-icon.py` | 小和图标生成器：沿用模型的橙色、方眼与四足轮廓，逐尺寸对齐像素边界，生成透明 SVG、1024px PNG 与 10 档 ICO（再生成需要 Pillow） |
| `public/icons/xiaohe.svg`、`public/icons/xiaohe.png` | 小和图标的矢量原稿与高清透明原图；程序、窗口、桌面和任务栏统一使用 `public/favicon.ico` |
| `tools/desktop-shortcut.ps1` | 通过 Windows Unicode 接口创建并读回验证快捷方式，避免简体中文路径在传统代码页下损坏；只更新相同目标的任务栏固定项 |
| `src/app/window-chrome.js`、`src/styles/window-chrome.css` | 本机窗口的液态玻璃标题栏：背景模糊、5px 边缘置换、高光、小和图标与窗口控制；普通浏览器不显示 |
| `tools/window_chrome.py` | 只允许当前本机主页操作窗口的窄接口，支持最小化、最大化／还原、关闭及带最小尺寸约束的八方向调整大小 |
| `tools/fetch-textures.mjs` | 表面贴图的唯一拉取脚本，来源与许可记录在内 |
| `tools/prepare-smart-books.mjs` | 馆藏清单的唯一生成器，写出 `book-inventory.json` 并核对它能原样展开 |
| `tests/library.test.mjs` | 馆藏几何、ASR 事件与 GLB 完整性回归检查 |
| `tests/book-query.test.mjs`、`tests/test_book_library.py` | 正文查询、持久化、章节导入、下载任务与 HTTP API 回归 |
| `tests/ui-smoke.mjs` | 界面冒烟测试（`npm run test:ui`）：无头 Chrome/Edge 跑完找书 → 翻开 → 芯片 → 放回 → 再找的完整链路 |
| `tests/server.test.mjs` | 本机服务的请求来源校验：设置与更新接口拒绝其它网页（CSRF）和重绑定到本机的域名 |
| `archive/prototype-single-file.html` | 原始单文件版本备份 |
| `archive/*.blend` | 植物精细化前 / 芯片体系前的源文件备份 |

玻璃标题栏的视觉参考：[HTML + CSS 实现 Liquid Glass 液态玻璃效果](https://juejin.cn/post/7514618352829448244)。背景透出馆内场景，边缘采用 SVG 置换与高光，中间保留可读的模糊透光区域；拖动与双击最大化使用 [WebView2 原生非客户区支持](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2settings9)。标题栏只在本机窗口启用，普通浏览器不添加窗口操作按钮。

## Blender 模型

打开 `blender/hexu-library.blend` 可编辑原始对象：书架按集合 `Shelf_1` 至 `Shelf_5` 组织，另有建筑、前台、阅读家具、绿植、灯具、书籍模板与渲染相机集合。源文件在合并之前保存，网页 GLB 按“集合 + 材质”合并，降低绘制调用数量。环境本身不导出静态藏书——已入库书籍来自 `shelf-book.glb` 的实例化；当前导出为 71 个网格、344,074 个三角面、**6.12 MiB**，精确统计见 `public/models/manifest.json`。毫米级书脊条纹在网页导出时简化倒角，源文件保留完整细节。

**几何用 Draco 压缩**（`KHR_draco_mesh_compression`，量化取位置 14 / 法线 10 / UV 12 位）。几何原本占文件的 74% 且是 float32，gzip 只能压到 59%；Draco 把它从 12.97 MiB 压到 **1.49 MiB**，且不损失任何视觉细节——比删减几何正确，因为那些面是植物的叶片。解码器 vendored 在 `public/vendor/draco/`，不经 CDN。加载实测（服务器上行 10 Mbps 是瓶颈）：首次约 6 秒，再次打开约 2 秒。

地板与书柜使用 **CC0 扫描的 PBR 贴图**（反照率 + 法线 + 粗糙度），取自 [Poly Haven](https://polyhaven.com)，由 `tools/fetch-textures.mjs` 拉取并随项目分发。地面为 200 mm 宽的实木板条，板长按列变化以错开对接缝；书柜为烟熏橡木。UV 按世界坐标投影，木纹在不同尺寸的构件上保持同一物理尺度——改前每个物体把整张贴图铺满自身尺寸，8 米层板上的木纹被拉伸到地板的 3 倍。两张贴图都不做染色：材质的色调靠选素材解决，染色是乘法，会把扫描件的对比度压平。素材来源、UV 取值与已知限制见 `blender/MATERIAL_REFERENCES.md`。

每个书架外围为 8 m 长 × 1 m 宽 × 2 m 高，但每个架面是进深 30 cm 的独立书柜，由一块实体背板与另一面隔开；书立在层板上并靠在背板上。进深取值依据见 `blender/SHELVING_REFERENCES.md`。

植物已升级为 6 盆鹤望兰形态盆栽与 26 丛黄杨形态灌木，包含 54 片曲面大叶及 14,144 片对生小叶。盆栽有叶脉纹理、弯曲叶柄、陶盆内壁、卷边与土壤颗粒；灌木通过分枝与叶片形成自然冠形。近景见 `blender/plant-detail.png` 和 `blender/hedge-detail.png`，图像由 Blender 实际渲染。

建模内容包括倒角木制层板、书架实体背板、框架立柱、黄铜层板包边、编号铭牌、弧角石台面、木条前台、软包座椅、台灯、植物叶片、窗框及悬吊灯具。木纹使用真实 UV 贴图并内嵌导出。动态阅读用书与 Blender 小和宠物由 Three.js 驱动，以支持拖动、实时文字和角色动画。

## 馆藏芯片与智能书

书架提供 11360 个槽位（5 架 × 双面 4 层 × 每面 4 个开间，每个开间约 70 个位置）；仅已导入或下载的书籍上架，**书脊朝外竖排**，用的是一块只有书脊与书口顶边的轻模板 `public/models/shelf-book.glb`（2 个网格部件、216 个三角面）。翻开阅读用的是另一块完整硬皮书模板 `public/models/smart-book.glb`（216 × 306 × 26 mm，含真正下凹的芯片槽、铜触点、硅片、镀金边框与保护窗；`FrontHinge` 是独立节点，翻开封面时绕书脊真实旋转）。

- 编号为 `HX-00001` 至 `HX-11360`，另有位置码 `S{架}-{A|B}-L{层}-P{槽}`（如 `S5-A-L3-P214`）；仅已入库书籍的编号与位置码可用于找书。
- 没有预置样书。未入库的编号仅表示空槽位，不可检索或取阅；真实书名、作者与正文由本地书库提供。
- 统一尺寸，只有布料不同：书脊宽 26 mm、高 306 mm（与阅读器同一块模板的尺寸，全馆统一）。同一尺寸的相邻 1–3 本共用一块布料色，那是成套的书；颜色在各架馆藏色上取十级色阶，所以一层是「一批布样里的书」而不是同一批染缸。
- 排架照真书架来：书脊贴着前口竖排，一行从左侧立柱起到行尾，余量留在行尾——不是均匀铺满。芯片刻印留在封面上，取书翻开时才能看见，这正是一本真的插在架上的书的样子。
- 网页端把两块模板各自实例化：架上是 2 个 `InstancedMesh`（书脊走逐实例着色，书口顶边保持纸色），阅读器另用完整硬皮书——所有已上架书籍共用 2 个绘制调用。
- 点击「查看芯片」会把书上的芯片放大成特写，展示编号、位置码与内部标记。

空槽位的位置由真实坐标决定，并由回归测试核对：每个槽位的 `worldPosition` 是对应层板顶面之上的自身中心、书口（前切口）抵住架内背板、书脊落在立柱之间的开间内且不越过黄铜包边，同一开间内的书首尾相接（缝小于 0.5 mm）、从左侧立柱起排、满容量时整行可容纳九成以上的书脊，每面每层 200 个以上的位置；实际显示数量取决于本地入库数量。进深与摆放依据见 `blender/SHELVING_REFERENCES.md`。

`tools/prepare-smart-books.mjs` 只生成空槽位的几何清单 `public/models/book-inventory.json`，格式为 3；每行 `[架, 面, 层, 槽, 布色, x, y, z]`，第 i 行对应 `HX-(i+1)`。清单不含预置书名、作者、简介或检索别名。真实书目和正文保存在程序目录之外的本地书库。

`library_deferred_ids` 是旧版本曾跳过的 12 个物理编号，仅用于保持历史槽位分配。`src/data/shelf-slots.js` 与本机语义服务遵守同一顺序：原有可用位置优先文学区，其余区域随后，这 12 个位置排到末尾。已有数据库的 slot、HX 编号和坐标均不变，无需迁移或重下正文。

```powershell
node tools/prepare-smart-books.mjs
```

改动馆藏坐标后应重跑该脚本并重建模型，避免书籍与槽位不一致。

每个书架结构的标称尺寸为 8m 长 × 1m 宽 × 2m 高，沿网页 Z 轴排列，四层、A/B 双面。装饰包边和铭牌允许毫米级外凸。五个架端引导点 X 为 `[-6,-3,0,3,6]`，前台点为 `[0,1.2,5]`。脚本将网页坐标 `(X,Y,Z)` 转为 Blender `(X,-Z,Y)`，glTF 导出再转回 Y 向上。

需要重建时：

```powershell
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python-exit-code 1 --python blender/build_library.py
```

该命令覆盖本项目生成的 `.blend`、`.glb`、纹理和预览。如果已在 Blender 手动修改源场景，请先另存后再运行。改动馆藏位置时，先重跑 `node tools/prepare-smart-books.mjs` 再重建，避免书籍与预留槽位不一致。

在 Blender 手动编辑并保存后，只更新网页模型和预览：

```powershell
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup blender/hexu-library.blend --python-exit-code 1 --python blender/export_saved.py
```

保留原有集合名称及材质，导出脚本据此分组。可取书的槽位由馆藏数据控制，移动书架时也应同步网页坐标。

## 验证

```powershell
npm test
```

回归测试覆盖五类契约：唤醒词与中英混排归一化、书名匹配的容错与误命中防线、11360 个空槽位的几何关系与旧书库位置兼容、`hexu-library.glb` 的合并网格与预算、`smart-book.glb` 的铰链与部件命名、唯一空槽位清单的体积与无预置内容约束、本机设置接口的来源校验，以及语音适配器的生命周期（模拟浏览器识别事件，不等同于真人麦克风转录验收）。实际语音测试请在 Chrome/Edge 打开 localhost 后授权执行。界面测试应覆盖：唤醒、找书、向左拖动封面、显示简介、查看芯片、归还后重新找书。

保留依赖文件中的版权及许可头。Three.js 使用 MIT 许可；GSAP 3.12.5 的许可链接保留于 `public/vendor/gsap.min.js` 开头；Draco 解码器使用 Apache-2.0，许可全文见 `public/vendor/DRACO-LICENSE.txt`。地板与书柜的贴图来自 Poly Haven，授权为 **CC0（公有领域）**，可自由分发，无需署名；素材标识记录在 `tools/fetch-textures.mjs` 与 `blender/MATERIAL_REFERENCES.md`。

## 书源兼容与文件导入

“正文书库 → 书源管理与导入”支持 CSS、XPath 1.0、JSONPath（含递归、通配与过滤）及纯 JavaScript 规则。JS 在 QuickJS 中执行，每次上限 0.5 秒、32 MiB 内存，不暴露文件、进程、环境变量或网络接口。支持 `@js:`、`<js>`、URL 的 `{{表达式}}`、`jsLib`、规则后的 JS 转换与 `##正则##替换`；XPath/JSONPath/CSS 可分别用于搜索、书籍信息、目录和正文。实现为自有兼容层，并非完整的 Legado 运行时。

导入成功后自动启用（若源原本 `enabled:false` 则保持停用），可在书源列表勾选开关。没有搜索规则的源标记“不提供搜索”，不再因 `ruleSearch:[]` 报错，也不会参加按书名搜索。在线正文通过书名搜索后下载并上架；本地文件使用 TXT / EPUB 导入。支持 `ruleBookInfo`、`ownText`、`href`、`@html`、目录及正文分页；存入书库的是清理后的纯文本。任一章节失败、分页循环或取消均不保存半本书。

当前边界：不提供阅读 App 的 `java.*`/`Packages.*`、Android 设备注册、Java 加密类、WebView 登录或验证码流程，也不完整实现 Legado 的所有组合选择器。依赖这些能力的源会列明原因并拒绝启用，不能把“支持 JS”当作全部 App 书源已兼容。以本次检查的“番茄小说(APP)”源为例，其正文依赖 Java 加密和设备注册，尚未适配；书海阁文件的目录及正文规则可被解析，但外站 HTTP 403 等服务状态仍可能阻止下载。

源码运行先安装解析依赖：

```powershell
python -m pip install -r tools/requirements-sources.txt
python -m unittest discover -s tests -p test_source_rules.py
```

桌面打包会自动安装并收集这些依赖。依赖文档：[QuickJS Python binding](https://pypi.org/project/quickjs-ng/)、[lxml XPath](https://lxml.de/xpathxslt.html)、[JSONPath-NG](https://pypi.org/project/jsonpath-ng/)。兼容语法参考 [Legado 解析器源码](https://github.com/LegadoTeam/legado/tree/master/app/src/main/java/io/legado/app/model/analyzeRule)，未复制该项目的实现代码。

## 小和的橙色像素宠物形态

小和已由光球改为按用户参考图制作的立体像素宠物：陶土橙方块身体、两只黑色方眼、两侧短手臂与四条短腿。模型在 Blender 5.2 中生成，独立的 [可编辑 Blender 文件](blender/xiaohe-pet.blend) 与 [四分之三视角渲染](blender/xiaohe-pet-three-quarter.png) 随源码保存；网页读取 `public/models/xiaohe-pet.glb`，没有用平面图片代替 3D 模型。

角色为 9 个网格、16 个节点、396 个三角面，GLB 约 35.2 KiB。待机悬浮、呼吸与眨眼，唤醒时抬手并放大、出现橙色波纹，找书与归还时摆腿飞行。原有语音与找书、封面、芯片、正文阅读流程继续使用。前台锚点与所有馆藏坐标未改。

生成模块 `blender/xiaohe_pet.py`、构建脚本 `blender/build_xiaohe_pet.py`、网页适配 `src/scene/companion.js`；形态量取、来源、独立重建与不变量验证见 [小和模型说明](blender/XIAOHE_PET_REFERENCES.md)。打包配置已携带新 GLB，旧桌面 EXE 要重新打包才能显示新形态。

## 小和像素对话

点击小和或说“小和”，会出现阶梯边框气泡与逐字显示的中文像素文字。气泡弹出和打字使用轻柔的本地合成音效，右下角 ▥ 可独立静音；♪ 保留语音播报开关。字体与授权文件随程序离线打包。也可以问“你是谁”“你能做什么”，或说“谢谢”“再见”。实现与素材来源见 [像素对话说明](docs/PIXEL_DIALOGUE.md)。


## 小和的联网搜索与网页阅读

小和可以按需调用 DeepSeek Search / Fetch 查询网页，并把资料交给对话模型生成回答。可说“小和，联网搜索今天的科技新闻”，或“小和，读取网页 https://example.com 并概括”。回答和可点击来源均显示在像素气泡中，不会自动打开对话面板。

模型设置中的「联网搜索与网页阅读」默认按需开启：官方 DeepSeek 对话直接复用已有密钥；换用其它 Chat Completions 对话服务后，可单独配置 DeepSeek 搜索密钥，或关闭联网。DeepSeek 思考模式仍关闭。每轮最多 3 次网页请求、2 轮工具调用，总时限沿用对话超时；失败会返回提示，不把失败当成查询成功。这两个接口用于问答取材，不负责将小说下载入库。

官方 Search / Fetch 当前各为每千次成功且有结果的请求 5 元，模型处理资料另计；费用以[官方指南](https://api-docs.deepseek.com/zh-cn/guides/search/)为准。配置和实现见 [联网工具说明](docs/WEB_TOOLS.md)。

## 小和的大模型对话

小和支持通过 API 自由问答与多轮追问：在「和 · 对话 → 模型设置」配置 DeepSeek 或其他 Chat Completions 兼容服务。普通问题由模型回答，找书与翻页仍走真实书库操作；所有回答在像素气泡完整逐字显示，支持滚动、显示全文与收起；语音提问不自动打开面板。DeepSeek 默认关闭思考模式。保存新的地址、模型与密钥后下一次提问生效，无需本机运行大模型。[配置、架构与数据边界](docs/LLM_BRAIN.md)。
