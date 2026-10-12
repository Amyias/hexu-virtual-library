# 和序 · 虚拟智能图书馆：技术实现与系统架构

> 分享说明：Markdown 请与 diagrams/ 文件夹一起移动；单独移动文件请选 TECHNICAL_GUIDE.html。三张配图在 HTML 内嵌，可离线阅读；源码链接指向 Gitee，访问私有仓库需要联网并登录。

> 文档日期：2026-10-12。源码基线：`2.3.0`，提交 `efe19c0`。本文根据当前源码、馆藏清单和导出清单整理，适合项目介绍、技术交接与演示准备。标为“建议”的内容尚未实现；数量与资源大小是该基线的数据，不代表未来版本。

## 1. 项目解决什么问题

和序图书馆把“说出需求、定位书籍、取书、阅读、归还”组织成一个可视化闭环。读者可以呼叫“小和”，也可以输入书名、编号、位置码或点击推荐入口。系统匹配到馆藏后，光球引导到书架，目标书飞到眼前；读者拖动封面翻开简介，还可以放大查看嵌入式芯片。

项目适合展示三维馆藏导览和语音交互。当前数据是预设目录：11,360 册中有 12 本具名演示书，其余为编号样书；阅读内容是书名、作者、分类与简介卡片。芯片是三维几何与数字标记，尚未对接真实 RFID、借还设备或图书馆业务数据库。

### 当前版本概况

| 项目 | 当前实现 |
| --- | --- |
| 书架 | 5 架，双面 A/B，各 4 层；每面分成 4 个开间 |
| 书架标称尺寸 | 长 8 m × 宽 1 m × 高 2 m；网页中沿 Z 轴延伸 |
| 馆藏数量 | 11,360 本，即 5 × 2 × 4 × 284；各开间约 70 本，按可用长度计算 |
| 统一书籍尺寸 | 216 × 306 × 26 mm；书脊朝外竖排 |
| 编号范围 | `HX-00001`～`HX-11360`；芯片编号与书籍编号相同 |
| 环境 GLB | 71 个网格、344,074 个三角面、6,419,832 字节，约 6.12 MiB |
| 架上藏书 | 2 个 `InstancedMesh` 实例池；书脊轻模板共 216 个三角面 |
| 植物 | 6 盆盆栽、26 丛灌木，含 54 片曲面大叶和 14,144 片小叶 |

数量来源为 [馆藏清单](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/public/models/book-inventory.json)、[导出统计](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/public/models/manifest.json) 和回归测试。早期“每面每层 8 本、共 320 本”的设计已经被该基线的密集竖排方案替代。

## 2. 系统架构

![系统架构：浏览器、可选后端与资产构建](diagrams/architecture.png)

[单独打开架构 SVG](diagrams/architecture.svg)。图中文字与连线均为矢量元素，可在支持 SVG 的工具中编辑，缩放时不损失清晰度。

若 Markdown 阅读器不显示 SVG，可打开 [架构图 PNG 预览](diagrams/architecture.png)。

系统由三部分组成：浏览器负责界面、馆藏匹配、状态和三维动画；可选 Python 后端提供本地模型识别、语义理解及桌面设置；Blender 与构建脚本负责生成模型、贴图、馆藏清单和发行包。静态站点可以独立运行，后端能力通过就绪接口自动探测。

### 主要模块及边界

| 文件 / 模块 | 职责 | 主要边界 |
| --- | --- | --- |
| `src/main.js` | 启动应用、显示加载异常 | 依赖或模型失败时给出可见提示 |
| `src/app.js` | 文本调度、唤醒、状态、取还动画 | 统一控制动作，避免各输入渠道直接改场景 |
| `src/voice/speech.js` | 识别器生命周期、候选、重连、记录 | 将转录结果送到 `processText` |
| `src/voice/server-asr.js` | 浏览器录音、断句、WAV 上传 | 启用前先探测 `/asr/ready` |
| `src/voice/intent.js` | 标题、别名、编号与位置匹配 | 返回目录内的实际书籍对象 |
| `src/voice/understand.js` | 语义请求与超时降级 | 放在应用调度层，不阻塞识别器同步派发 |
| `src/scene/runtime.js` | 渲染器、相机、环境光、阴影 | 统一米制坐标和渲染设置 |
| `src/scene/environment.js` | 环境与两种书籍模板加载 | 连接 Draco 解码器与书架实例化 |
| `src/scene/smart-books.js` | 海量书脊实例、逐本颜色与显隐 | 取书时只隐藏目标实例，归还时恢复 |
| `src/scene/orb.js` | 光球 Shader、光晕和环形波纹 | 由时间与唤醒强度驱动视觉反馈 |
| `src/reader/book.js` | 完整书克隆、铰链、文字、芯片特写 | 阅读结束释放动态生成的资源 |
| `tools/asr-server.py` | HTTP 静态资源、ASR 与语义服务 | 同一入口支持服务器和打包程序模式 |
| `tools/window_host.py` | Windows 原生窗口 | pywebview / WebView2 承载同一网页 |
| `tools/updater.py` | 桌面发行包更新 | 下载、校验、退出后替换与重启 |

## 3. 用了哪些技术，分别如何工作

| 技术 | 本项目中的用途 | 为什么采用 |
| --- | --- | --- |
| HTML5 / CSS3 | 页面、搜索、控制按钮、气泡、响应式布局 | 文字和控件易读，不必全部做成三维对象 |
| JavaScript ES Modules / import map | 模块拆分及本地依赖映射 | 通过 HTTP 直接加载，静态开发不需要前端打包器 |
| Three.js `0.160.1` / WebGL | 场景、相机、材质、灯光与拾取 | 用 JavaScript 控制实时三维渲染 |
| GLSL / ShaderMaterial | 光球流动色彩、形变和唤醒高亮 | 每帧在 GPU 上计算表面效果 |
| GSAP `3.12.5` | 光球、相机、书籍的位置与旋转动画 | 对多个动画做时间编排和缓动 |
| Blender 5.2 / Python `bpy` | 程序化精细建模、局部替换、导出、渲染 | 保留可编辑源场景，使生成过程可复现 |
| glTF 2.0 / GLB | 环境、书脊和阅读书的运行资源 | 保存几何、材质、纹理与节点层级 |
| Draco / DRACOLoader | 压缩和解码环境几何 | 减少传输体积；解码器随项目分发 |
| GPU Instancing | 将同一书脊模板绘制 11,360 次 | 每册主要提供变换与颜色数据 |
| Canvas 2D / CanvasTexture | 中文封面、简介页、芯片文字 | 动态生成不同书目的文字纹理 |
| Web Speech API | 浏览器识别和可选语音播报 | 无需部署识别后端的路径 |
| getUserMedia / Web Audio | 录音、音量计算、断句与重采样 | 为自有后端准备固定格式的音频 |
| Python / sherpa-onnx / SenseVoice | 后端主机上的 ONNX 语音推理 | 在浏览器识别服务不可达时提供另一条路径 |
| HTTP JSON / 大模型接口 | 将规则读不懂的话转换为受约束的意图 | 覆盖长尾表达，返回后校验编号 |
| Node.js | 静态服务、生成清单、测试、打包与发行脚本 | 静态服务和回归测试使用内置模块 |
| PyInstaller / pywebview / WebView2 | 打包可双击运行的 Windows 程序 | 分发 Python 运行时、站点和识别模型 |

版本说明：建模统计记录 Blender `5.2.2 LTS`；打包脚本列出的构建依赖包括 PyInstaller `6.22.3`、sherpa-onnx `1.13.8` 和 NumPy。这些是项目内记录的版本，不表示运行本机已安装全部依赖。

## 4. 语音唤醒、识别与理解

![语音识别、意图解析与取还流程](diagrams/voice-flow.png)

[SVG 原图](diagrams/voice-flow.svg) · [PNG 预览](diagrams/voice-flow.png)

### 4.1 两种识别通道

**浏览器通道。** 使用 `SpeechRecognition` / `webkitSpeechRecognition`，语言为 `zh-CN`，设置 `continuous = true`、`interimResults = true`、`maxAlternatives = 5`。中间转录可以提前触发光球脉冲，最终结果进入需求处理。识别结束后按状态尝试重连；页面可见性、用户关闭操作与权限错误会影响重启。这里的“持续”是应用维持监听生命周期，并非操作系统级的全天候后台唤醒服务。

**后端通道。** 页面先探测 `/asr/ready`；后端就绪时用 `getUserMedia` 获取麦克风，经 Web Audio 采集帧、按 RMS 能量判断语音与静默，编码成 16 kHz、单声道、16 位 PCM WAV，发送到 `POST /asr`。当前以 1024 样本为一帧，目标采样率下约 64 ms；约 0.7 秒静默结束一段，最长分段约 15 秒，并保留约 0.25 秒预录音。浏览器未采用请求的采样率时进行线性重采样，实际断句时间会随采样率变化。

后端用 sherpa-onnx 加载 SenseVoice INT8 ONNX 模型，NumPy 转换音频；解码通过互斥锁串行执行。接收端检查 WAV 格式、请求体大小及 0.25～45 秒时长。前端发起识别请求时暂停收集新帧，因此该通道有句尾延迟和请求期间的收音空档，目前不是流式实时识别。

### 4.2 唤醒与多轮承接

1. 转录包含“小和”或别名（小何、肖和、小荷、小河、晓和、小禾、小鹤、`xiao he`）时触发唤醒。
2. 单独呼叫时只回应“有什么需求吗？”，设置 25 秒等待窗口，并播放光球脉冲；保持前台位置。
3. 在窗口内说出需求，不必重复唤醒词；一句“小和，帮我找三体”也能直接完成匹配与导航。
4. 搜索框和按钮属于直接输入，跳过唤醒门控，但仍经过统一调度与状态检查。
5. 阅读中支持翻开、合上、查看芯片、放回等指令；语音输入仍需满足唤醒或有效等待窗口，按钮与键盘不受该条件限制。

监听偏好保存在浏览器本地。首次启用仍受浏览器或原生窗口的麦克风权限机制约束；后续能否自动恢复取决于权限持久化、浏览器策略和窗口环境。

### 4.3 本地规则优先，可选语义兜底

`intent.js` 先归一化空白、标点和大小写，并预先构造候选索引。匹配优先级为完整标题 / 别名命中、片段命中、编辑距离不超过 1 的近似命中；同级优先书名，再按目录顺序决定。查询太短时限制近似匹配，二字书名不做近似，以减少“身体”“三国”等误命中《三体》的情况。识别器提供的多个候选也参与匹配。

规则未命中且 `/understand/ready` 就绪时，应用才调用语义层。后端把具名目录摘要、编号规则、当前状态与读者文本交给配置的大模型 `/chat/completions` 接口；限制其输出 `find / return / open / close / chip / none`。后端检查 `bookId` 确实存在，前端再查找对应馆藏对象后执行。模型不可用、超时或结果不合法时退回未匹配提示。前端预算 15 秒，后端模型请求默认预算 12 秒。

这使“霍金写的那本”有机会映射到《时间简史》，但并不构成全馆语义检索或推荐系统：当前大部分藏书没有真实元数据，也没有向量索引。

## 5. 三维场景、模型与性能

![从 Blender 制作到网页加载的资产管线](diagrams/asset-pipeline.png)

[SVG 原图](diagrams/asset-pipeline.svg) · [PNG 预览](diagrams/asset-pipeline.png)

### 5.1 环境与渲染

Blender 保存建筑、书架、家具和植物的源对象；导出时按集合与材质合并网格。前端使用 `GLTFLoader` 加载 GLB，通过项目内的 Draco 解码器解压环境几何。

`runtime.js` 建立透视相机、半球光、方向光和阴影，使用 sRGB 输出及 ACES 色调映射；像素比限制到 2，避免高分辨率设备无限增加像素开销。`RoomEnvironment` 与 PMREM 提供环境反射。地板和书柜使用反照率、法线、粗糙度 PBR 贴图；木纹按物理尺度映射，来源和 CC0 许可见 [材质说明](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/blender/MATERIAL_REFERENCES.md)。

光球由程序化 Shader、加法混合光晕和环形几何共同组成。时间控制色彩流动和待机浮动，唤醒参数提高亮度、尺寸和波纹强度，再由 GSAP 逐渐衰减。

### 5.2 为什么使用两块书籍模板

架上主要看得到书脊与书口顶边，因此 `shelf-book.glb` 只保留两个网格部件；每个部件各建立一个 `InstancedMesh`。取书时通过把目标实例矩阵缩放为零来隐藏它，归还时恢复原矩阵。

居中阅读使用完整的 `smart-book.glb`，包含纸页、封板、芯片凹槽和独立 `FrontHinge`。架上轻模板与阅读模板共用同一本书的编号、颜色、尺寸和位置数据，但几何细节层次不同，避免把芯片和铰链复制到每一本架上书。

“2 个绘制调用”仅描述当前两个架上实例池在主要颜色绘制中的规模；环境、光球、阅读器和其他渲染工作仍有各自成本。实例化不会消除总三角面、像素着色与内存成本。当前代码关闭架上书的投射阴影并关闭实例池的视锥剔除，大规模场景仍需要实际 GPU 测量。

### 5.3 取书与翻页

应用状态链是 `IDLE → NAVIGATING → PRESENTING → READING → RETURNING → IDLE`。导航先使光球到书架引导点，再高亮具体书籍。书的起点来自该册的真实 `worldPosition`，完整模型飞到相机前，阅读时允许翻页和芯片特写。归还时先合上封面，飞回书位并恢复架上实例，再把光球和视角送回待机状态。

指针按下后用 Raycaster 判断是否点中书籍；水平拖动距离映射到 `turn ∈ [0,1]`，并设置 `hinge.rotation.y = -π × turn`。因此封面绕书脊铰链从 0° 转到 -180°。松开后吸附到开或合状态，也可用按钮与左右方向键操作。介绍页和封面文字由 Canvas 生成，内容不是书籍全文。

## 6. 馆藏数据与芯片定位

馆藏由 `tools/prepare-smart-books.mjs` 统一生成，写入三份副本：

- `src/data/catalog.js`：前端加载并构建检索索引。
- `public/models/book-inventory.json`：HTTP 和后端读取。
- `blender/catalog.json`：Blender 放置书籍、生成标记。

12 本示例书的位置来自 `blender/demo-shelf-map.json`；生成器根据开间实际长度、立柱位置和 26 mm 书厚计算容量。每行共 284 本，位置码里的 `P` 表示该面该层的全行槽位，并非某个开间内的第几本。

| 数据字段 | 作用 |
| --- | --- |
| `bookId` / `chipId` | 藏书与芯片一一对应的编号 |
| `title` / `author` / `category` / `synopsis` | 检索、封面与简介页 |
| `shelf` / `side` / `layer` / `slot` | 可读的存放位置 |
| `locationCode` | 紧凑位置码，例如 `S1-A-L1-P001` |
| `worldPosition` | 该书中心在网页世界中的真实 `[x,y,z]` 坐标 |
| `widthScale` / `heightScale` / `depthScale` | 模板缩放参数；当前统一尺寸取 1 |
| `chipPayload` | 编号、书架、面、层、槽位和位置码的结构化副本 |
| `placeholder` | 是否为只有编号的样书 |

网页坐标 `(X,Y,Z)` 对应 Blender 的 `(X,-Z,Y)`。前台待机点为 `[0,1.2,5]`，五个架端引导点的 X 为 `[-6,-3,0,3,6]`。响应协议中的 `target.world_position` 是光球的书架引导点；具体书籍飞出与归位使用 `book.worldPosition`，两者应分别理解。

芯片的硅片、铜触点、边框和保护窗是完整模板里的真实网格；编号、位置码在网页中用 CanvasTexture 绘制，Blender 源文件可保留相应微文字。当前位置来自预设目录，不是芯片实时测距得到的结果。将来对接真实馆藏时，建议把稳定的书籍编号和会变化的存放位置分开管理，避免移架后旧位置仍被当作事实。

## 7. 接口与运行模式

### 7.1 运行模式对比

| 模式 | 如何运行 | 语音识别位置 | 适合场景 |
| --- | --- | --- | --- |
| 静态开发 | `npm start`，默认 `http://localhost:8080` | 浏览器识别服务 | 三维演示、文字找书、前端开发 |
| Python 后端 | `tools/asr-server.py`，默认 `127.0.0.1:8090`；需模型和依赖 | 运行 Python 的主机 | 本地 ASR、可选语义服务 |
| Windows 桌面程序 | PyInstaller 打包；WebView2 窗口或 `--browser` | 用户电脑内置模型 | 无需开发环境的使用者 |

静态资源与渲染库随项目分发，3D 浏览和文字找书不依赖 CDN。静态模式的浏览器语音可能依赖厂商网络服务；桌面本地 ASR 的音频在本机处理；如果后端部署在另一台服务器，录音则发送到那台服务器。启用大模型语义层时，文本与目录摘要会发送到所配置的模型服务。

### 7.2 后端接口摘要

| 方法 / 路径 | 输入 / 输出 | 作用 |
| --- | --- | --- |
| `GET /healthz` | 应用标识、ASR 和语义就绪状态 | 启动探测和健康检查 |
| `GET /asr/ready` | 识别能力及未就绪原因 | 前端选择识别通道 |
| `POST /asr` | PCM WAV → `{text, ...}` | 音频转录 |
| `GET /understand/ready` | 语义配置就绪情况 | 决定是否启用理解兜底 |
| `POST /understand` | `{text, phase}` → `{action, bookId, say, ...}` | 受约束的意图解析 |
| `GET /settings`、`GET /settings/state` | 设置页、脱敏状态 | 本机配置入口 |
| `POST /settings/key`、`POST /settings/test` | 保存配置、连接测试 | 仅回环访问 |
| `GET /update/status`、`GET /update/progress` | 版本与更新进度 | 仅回环访问 |
| `POST /update/apply` | 启动更新流程 | 仅回环访问 |

这些接口由 Python 后端提供，`npm start` 的 Node 服务只提供静态文件。Python 服务默认绑定回环地址，使用预压缩 `.gz` 副本和 ETag / 304 减少重复传输；接口就绪并不等同于已完成真实麦克风测试。

应用另通过 `xiaohe-response` 事件公布找书 / 唤醒协议，字段为 `speech`、`is_wake_only`、`action`、`target` 与 `book_data`。这是前端业务响应，与语义接口的 `action/bookId/say` 是两份不同契约。消费该事件时应先判断 `action`；`IDLE` 的目标字段是无动作占位，不应触发移动。

### 7.3 桌面版与更新

打包脚本准备虚拟环境、校验模型、暂存站点、预压缩资源，再调用 PyInstaller；Windows 窗口由 pywebview / WebView2 承载。`window_host.py` 为应用页处理麦克风权限，缺少原生组件时退回系统浏览器。

源码提交推送到 GitHub，Gitee 保留同步入口；桌面更新器读取 **GitHub Releases**，下载程序包，校验摘要，在退出后由辅助脚本替换并重启。模型包与程序包分开，有模型的安装可保留模型，减少重复下载。Gitee 的 `master` 不包含完整 ASR 模型；构建还需另行准备模型，或具备可读取的模型分支。配置见 [部署说明](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/DEPLOY.md)。

**发布维护规则更新（2026-10-12）**：每个发行版都必须提供程序 ZIP 与模型 ZIP，即使模型内容未变。新版本先创建草稿，两个附件的状态、大小与 SHA-256 校验通过后才正式发布；历史模型仅作为更新器兼容兜底。补模型使用 `--assets-only --model-only`，不替换程序、不移动标签；`--no-model` 只能用于当前发行版已经存在完整模型附件的情况。源码 `git push` 与上传 Release 附件是两个独立步骤，模型 ZIP 不进入 `master` 历史。

用户设置保存在仓库外的用户配置目录，避免升级覆盖；源码、文档、日志与 HTTP 状态接口不应包含密钥原文。本文只说明配置机制，不包含实际凭据。

## 8. 如何运行、验证和维护

### 最小运行

在项目根目录执行：

```powershell
npm start
```

打开 `http://localhost:8080`，先用文本搜索确认模型和取还链路，再授权测试语音。不要直接双击 `index.html`，ES Modules 和模型加载需要 HTTP 环境。Node.js 静态入口不需要安装 npm 依赖；馆藏生成器还使用 JSON import attributes，执行生成脚本前应确认所用 Node 版本支持该语法。

### 自动与人工验收

```powershell
npm test
```

原基线的 9 项测试覆盖唤醒词与检索容错、误命中防线、馆藏排架与三份清单一致性、环境 GLB、阅读模板节点、植物纹理、ASR / 语义探测降级及识别生命周期。此次发布规则维护增加 3 项附件策略测试，`npm test` 共 12 项；另用 `python -m unittest discover -s tests -p test_archive.py` 验证真实 ZIP 及缺失/空模型文件拒绝路径。识别生命周期使用模拟事件，不能据此宣称真人语音准确率、噪声鲁棒性或端到端延迟已达标。

人工演示建议依次检查：

1. 场景加载完成，可旋转、缩放，五个分区正常显示。
2. 单说“小和”，出现指定气泡和光球脉冲，位置保持前台。
3. 先唤醒再说书名，以及一句话唤醒加需求，均能匹配。
4. 取书后原书位变空，书籍居中，向左拖动可翻开简介。
5. 芯片编号、位置码与当前书目一致，关闭特写后能继续阅读。
6. 归还后书位恢复、光球回前台，并能再次检索。
7. 关闭麦克风、拒绝权限、后端未部署、语义服务失败时，文字找书仍可用。

### 修改模型或馆藏时

先明确数据或部件边界，保留源文件和备份；调整坐标后生成三份清单，再在临时副本重建，比较几何与位置不变量，验证后替换成品。仅改模型源文件而未更新 GLB，或仅改一份清单，都可能造成架上书、阅读书和芯片位置不一致。工作约定见 [DEVELOPMENT.md](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/DEVELOPMENT.md)。

本文附带的三张 SVG 可重新生成：

```powershell
node docs/generate-diagrams.mjs
```

## 9. 设计取舍与当前限制

| 选择 / 限制 | 好处 | 需要理解的代价 |
| --- | --- | --- |
| 本地规则优先 | 常见需求即时响应，减少外部请求 | 复杂表达需要可选语义服务；多解时当前按优先级取首个结果 |
| 双书籍模板 | 万册排架保持较少绘制调用，阅读仍有细节 | 架上几何为书脊表示，不能当成完整实体书直接任意翻转观察 |
| 静态目录三份副本 | 前端、后端、Blender 各自读取方便 | 必须依靠唯一生成器和一致性测试同步 |
| 应用状态统一调度 | 减少重复取书、动画重叠和资源泄漏 | 当前一次主要阅读一本，尚无多用户借阅事务 |
| 能量阈值断句 | 实现简单，不额外加载 VAD 模型 | 噪声影响阈值；段式请求有句尾延迟和收音空档 |
| Web Audio ScriptProcessor | 当前录音实现可工作 | 后续可评估迁移 AudioWorklet，减少主线程音频处理压力 |
| 实时简介纹理 | 支持中文元数据 | 不是 EPUB / PDF 阅读器，不支持连续全文翻页 |
| Python 轻量 HTTP 服务 | 静态文件和识别易于一起部署 | 尚不是具备多租户认证、限流和持久化事务的公共平台 |
| GLB 几何压缩 | 减少模型传输体积 | 解码仍有 CPU 开销；纹理和目录也占内存与带宽 |

本次文档工作没有对帧率、首次加载时间、真实语音准确率、外部模型接口或桌面自动更新执行新的现场验收。文档中的现有能力以源码为依据，性能结论需要在目标设备和网络上另行测量。

## 10. 建议下一步补齐什么

以下是后续开发建议，不是当前已完成的功能，可以作为需求讨论清单。

| 优先级 | 建议 | 解决的问题 | 可验证的交付目标 |
| --- | --- | --- | --- |
| P0 | 真实书目导入与持久化 | 样书无法用于实际业务，更新目录依赖脚本 | 导入 ISBN、作者、分类与副本编号，提供重复校验、增量更新及回滚 |
| P0 | 多结果确认与消歧 | 同一主题、同名书或作者可能匹配多本 | 展示候选列表，读者确认后再导航 |
| P0 | 语音验收数据集 | 目前无法量化“好不好用” | 固定指令集，测唤醒召回、误唤醒、匹配准确率和 P50/P95 延迟 |
| P1 | AudioWorklet + 更稳健 VAD | 噪声断句和收音空档影响体验 | 对噪声和长句测试；明确请求排队、超时和取消策略 |
| P1 | 位置版本与实体 RFID 映射 | 数据目录不能证明实体书实时位置 | 分开管理 bookId、tagId、location 与时间戳，处理读写器事件及过期数据 |
| P1 | 性能与可访问性 | 设备配置不同，部分读者不便使用 3D | 记录 GPU 帧时间与内存，提供低画质、减少动态效果、纯列表与键盘路径 |
| P1 | 后端公开部署加固 | 回环单机设计不能直接等同于公共服务 | 添加身份验证、请求限额、音频保留策略和多用户会话隔离 |
| P2 | EPUB / PDF 阅读与版权边界 | 目前只能看简介 | 确认内容授权，再设计页码、书签、字体、搜索与阅读进度 |
| P2 | 自动交互回归与资产版本 | 现有测试没有跑完整 UI 动画 | CI 验证取书 / 翻页 / 芯片 / 归还；为资产与目录生成统一版本和摘要 |
| P2 | 借阅与运营后台 | 当前没有借阅业务闭环 | 明确读者身份、借还状态、预约、审计与异常纠正，再设计数据库和接口 |

建议先确定主要使用场景：课堂展示、展馆导览、个人桌面馆藏或正式图书馆业务。不同场景对真实性、并发、隐私、内容授权和硬件对接的投入差异很大，先选场景再决定路线更容易得到可验收的结果。

## 11. 汇报与演示可以如何组织

可以按“需求 → 用户体验 → 架构 → 技术难点 → 验证 → 下一步”讲解，而不是只罗列框架名称。演示主线建议选《三体》：独立唤醒、找书、目标高亮、飞出、拖动封面、看芯片、归还；再用编号查询证明位置与芯片标记贯通。

适合强调的工程点包括：识别与意图分层、同一调度入口承接多种输入、海量书脊实例与单本精细模型分工、唯一馆藏生成器连接建模与前端、模型返回编号的双重校验，以及后端能力缺失时的降级路径。演示前先说明真实书目数量与样书范围，避免把三维展示误讲成已经接入实际借还系统。

## 12. 源码核对入口

本文的实现描述主要依据下列源码，后续升级时可从这些入口复核：

- 场景：[runtime.js](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/src/scene/runtime.js)、[environment.js](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/src/scene/environment.js)、[smart-books.js](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/src/scene/smart-books.js)、[orb.js](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/src/scene/orb.js)。
- 交互：[app.js](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/src/app.js)、[book.js](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/src/reader/book.js)。
- 语音：[speech.js](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/src/voice/speech.js)、[server-asr.js](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/src/voice/server-asr.js)、[intent.js](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/src/voice/intent.js)、[understand.js](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/src/voice/understand.js)。
- 服务与发行：[asr-server.py](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/tools/asr-server.py)、[window_host.py](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/tools/window_host.py)、[package-local.mjs](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/tools/package-local.mjs)、[updater.py](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/tools/updater.py)、[release.mjs](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/tools/release.mjs)。
- 数据与验收：[prepare-smart-books.mjs](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/tools/prepare-smart-books.mjs)、[manifest.json](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/public/models/manifest.json)、[library.test.mjs](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/tests/library.test.mjs)。
- 使用与维护：[README.md](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/README.md)、[DEPLOY.md](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/DEPLOY.md)、[DEVELOPMENT.md](https://gitee.com/li-tao-yi/hexu-virtual-library/blob/efe19c0ce5fea3df10b1929952d9fcbdf8ea715b/DEVELOPMENT.md)。
