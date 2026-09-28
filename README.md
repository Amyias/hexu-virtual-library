# 和序 · 虚拟智能图书馆

Blender 精细环境模型 + Three.js 网页交互。此版本已从单文件拆分为 ES Modules，模型、贴图及渲染依赖均保存在项目中。

## 运行

已安装 Node.js 18 或更高版本时，在项目目录执行：

```powershell
npm start
```

打开 `http://localhost:8080`。不需要 `npm install`。不能直接双击 `index.html`：浏览器模块与 GLB 资源需要通过 HTTP 服务加载。

首次点击“启动语音感知”并允许麦克风，然后说“小和”或“小和，帮我找三体”。支持同音词、多轮承接、自动重连和关闭监听。Web Speech API 的实际可用性取决于浏览器、权限与语音服务网络；3D 场景及本地文字找书不依赖外部 CDN。语音播报可通过 ♪ 开启。

书名匹配带容错：三字以上的书名差一个字（「时间减史」→《时间简史》）或只说其中一段（「计算机」→《计算机基础》）都能命中，识别器返回的多个候选会一并参与匹配。二字书名只做精确匹配——编辑距离分不出同音与不同音，放开会让「身体」「三国」「沙发」这类常用词误命中，因此「三题」这类错字交由候选列表救回。帮助面板底部的「最近识别记录」会列出听到的原文、实际采用的候选与是否命中，用来分辨是识别错了还是没匹配上。

## 文件结构

| 路径 | 职责 |
| --- | --- |
| `DEVELOPMENT.md` | 开发与提交约定、远端仓库与凭据位置，动手前先读 |
| `AGENTS.md` | 约定要点，供自动化代理读取 |
| `index.html` | 页面结构、import map、本地依赖入口 |
| `src/main.js` | 启动与资源加载错误提示 |
| `src/app.js` | 唤醒、导航、阅读、芯片特写、归还的状态与动画编排 |
| `src/data/catalog.js` | 320 枚编号芯片馆藏（含 12 本示例书）、位置与检索关键词 |
| `src/voice/intent.js` | 唤醒词与馆藏匹配 |
| `src/voice/speech.js` | Web Speech API 生命周期和识别事件 |
| `src/scene/runtime.js` | 相机、光照、阴影、环境反射 |
| `src/scene/environment.js` | 加载 Blender GLB、悬浮分类标识、书架实例化入口 |
| `src/scene/smart-books.js` | 320 本书的 GPU 实例化与芯片刻印图集 |
| `src/scene/orb.js` | 小和流光 Shader、呼吸与唤醒波纹 |
| `src/reader/book.js` | 绕书脊铰链开合、封面与中文简介纹理、芯片特写模型 |
| `src/styles/library.css` | 页面与响应式布局 |
| `blender/hexu-library.blend` | 可直接在 Blender 编辑的源场景 |
| `blender/build_library.py` | 可重复执行的建模、导出、渲染脚本 |
| `blender/export_saved.py` | 从已保存的源模型重新导出，不重建或覆盖源文件 |
| `blender/smart_books.py` | 硬皮书模板（下凹芯片槽）建模、`smart-book.glb` 导出、320 本书实例化 |
| `blender/refine_books.py` | 定点更新书籍，备份、导出并渲染书本、芯片与书架内景 |
| `blender/vegetation.py` | 盆栽曲面叶片、叶脉、陶盆与灌木分枝建模 |
| `blender/refine_vegetation.py` | 定点更新植物，核验其余模型不变，导出并渲染近景 |
| `blender/BOTANICAL_REFERENCES.md` | 植物形态参考、生成参数与更新方法 |
| `blender/SHELVING_REFERENCES.md` | 书架进深标准、图书摆放方式与更新方法 |
| `blender/MATERIAL_REFERENCES.md` | 地板与书柜的材质来源、UV 尺度与更新方法 |
| `blender/catalog.json` | 320 本书的坐标与芯片载荷（生成物） |
| `blender/library-preview.png` | Blender 实际渲染的场景预览 |
| `blender/smart-book-detail.png` | 书本与芯片槽近景渲染 |
| `blender/chip-detail.png` | 芯片微刻字近景渲染 |
| `blender/shelf-detail.png` | 书架内景：书立在层板上、靠住背板 |
| `public/models/hexu-library.glb` | 网页使用的合并材质环境模型（不含架上藏书） |
| `public/models/smart-book.glb` | 320 本书共用的硬皮书模板 |
| `public/models/book-inventory.json` | 馆藏清单副本（与 `blender/catalog.json` 一致） |
| `public/models/manifest.json` | 导出版本、书架规格、面数、文件大小 |
| `public/textures/floor-oak-*.jpg` | 地板贴图（反照率 / 法线 / 粗糙度），CC0 扫描件 |
| `public/textures/joinery-oak-*.jpg` | 书柜与木作贴图（同上） |
| `public/textures/botanical-leaf.png` | Blender 生成的叶片贴图，同时内嵌于 GLB |
| `public/vendor/` | Three.js 0.160.1、GLTFLoader、GSAP 3.12.5 等固定依赖 |
| `tools/serve.mjs` | 无额外依赖的本地静态服务 |
| `tools/fetch-textures.mjs` | 表面贴图的唯一拉取脚本，来源与许可记录在内 |
| `tools/prepare-smart-books.mjs` | 馆藏清单的唯一生成器，一次写入三份副本 |
| `tests/library.test.mjs` | 馆藏几何、ASR 事件与 GLB 完整性回归检查 |
| `archive/prototype-single-file.html` | 原始单文件版本备份 |
| `archive/*.blend` | 植物精细化前 / 芯片体系前的源文件备份 |

## Blender 模型

打开 `blender/hexu-library.blend` 可编辑原始对象：书架按集合 `Shelf_1` 至 `Shelf_5` 组织，另有建筑、前台、阅读家具、绿植、灯具、书籍模板与渲染相机集合。源文件在合并之前保存，网页 GLB 按“集合 + 材质”合并，降低绘制调用数量。环境本身不导出静态藏书——架上 320 本书全部来自 `smart-book.glb` 的实例化；当前导出为 70 个网格、340,010 个三角面、17.54 MiB，精确统计见 `public/models/manifest.json`。毫米级书脊条纹在网页导出时简化倒角，源文件保留完整细节。

地板与书柜使用 **CC0 扫描的 PBR 贴图**（反照率 + 法线 + 粗糙度），取自 [Poly Haven](https://polyhaven.com)，由 `tools/fetch-textures.mjs` 拉取并随项目分发。地面为 200 mm 宽的实木板条，板长按列变化以错开对接缝；书柜为烟熏橡木。UV 按世界坐标投影，木纹在不同尺寸的构件上保持同一物理尺度——改前每个物体把整张贴图铺满自身尺寸，8 米层板上的木纹被拉伸到地板的 3 倍。两张贴图都不做染色：材质的色调靠选素材解决，染色是乘法，会把扫描件的对比度压平。素材来源、UV 取值与已知限制见 `blender/MATERIAL_REFERENCES.md`。

每个书架外围为 8 m 长 × 1 m 宽 × 2 m 高，但每个架面是进深 30 cm 的独立书柜，由一块实体背板与另一面隔开；书立在层板上并靠在背板上。进深取值依据见 `blender/SHELVING_REFERENCES.md`。

植物已升级为 6 盆鹤望兰形态盆栽与 26 丛黄杨形态灌木，包含 54 片曲面大叶及 14,144 片对生小叶。盆栽有叶脉纹理、弯曲叶柄、陶盆内壁、卷边与土壤颗粒；灌木通过分枝与叶片形成自然冠形。近景见 `blender/plant-detail.png` 和 `blender/hedge-detail.png`，图像由 Blender 实际渲染。

建模内容包括倒角木制层板、书架实体背板、框架立柱、黄铜层板包边、编号铭牌、弧角石台面、木条前台、软包座椅、台灯、植物叶片、窗框及悬吊灯具。木纹使用真实 UV 贴图并内嵌导出。动态阅读用书与能量光球仍由 Three.js 驱动，以支持拖动与实时文字。

## 馆藏芯片与智能书

架上 320 本书（5 架 × 双面 4 层 × 每面每层 8 本）共用同一个 Blender 硬皮书模型 `public/models/smart-book.glb`：216 × 306 × 26 mm，含真正下凹的芯片槽、铜触点、硅片、镀金边框与保护窗。`FrontHinge` 是独立节点，翻开封面时绕书脊真实旋转。

- 编号为 `HX-0001` 至 `HX-0320`，另有位置码 `S{架}-{A|B}-L{层}-P{槽}`（如 `S5-A-L3-P08`）；编号与位置码都能直接用来找书。
- 其中 12 本有真实书名、作者与简介，其余为编号样书。
- 网页端按网格部件各建一个 `InstancedMesh`，封面颜色走逐实例着色；封面刻印是 4096 × 2560 的 Canvas 图集（16 × 20 格，恰好 320 格），由 `atlasOffset` 实例属性采样。因此 320 本书只占 45 个绘制调用（44 个网格部件 + 芯片图集）。
- 点击「查看芯片」会把书上的芯片放大成特写，展示编号、位置码与内部标记。

书的位置由真实坐标决定，并由回归测试核对：每本书的 `worldPosition` 必须正好落在对应层板的顶面上、书背贴合架内背板、位于立柱之间的开间内，且每面每层恰好 8 本。进深与摆放依据见 `blender/SHELVING_REFERENCES.md`。

`tools/prepare-smart-books.mjs` 是馆藏清单的唯一生成器，一次写入三份必须完全一致的副本：`blender/catalog.json`、`public/models/book-inventory.json`、`src/data/catalog.js`。它从当前清单继承那 12 本示例书，因此调整示例书目后需要重跑并核对数量：

```powershell
node tools/prepare-smart-books.mjs
```

改动馆藏坐标后应重跑该脚本并重建模型，避免书籍与槽位不一致。

每个书架结构的标称尺寸为 8m 长 × 1m 宽 × 2m 高，沿网页 Z 轴排列，四层、A/B 双面。装饰包边和铭牌允许毫米级外凸。五个架端引导点 X 为 `[-6,-3,0,3,6]`，前台点为 `[0,1.2,5]`。脚本将网页坐标 `(X,Y,Z)` 转为 Blender `(X,-Z,Y)`，glTF 导出再转回 Y 向上。

需要重建时：

```powershell
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python-exit-code 1 --python blender/build_library.py
```

该命令覆盖本项目生成的 `.blend`、`.glb`、纹理和预览。如果已在 Blender 手动修改源场景，请先另存后再运行。改动馆藏位置时，应同步 `src/data/catalog.js` 和 `blender/catalog.json` 并重建，避免书籍与预留槽位不一致。

在 Blender 手动编辑并保存后，只更新网页模型和预览：

```powershell
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup blender/hexu-library.blend --python-exit-code 1 --python blender/export_saved.py
```

保留原有集合名称及材质，导出脚本据此分组。可取书的槽位由馆藏数据控制，移动书架时也应同步网页坐标。

## 验证

```powershell
npm test
```

回归测试覆盖五类契约：唤醒词与中英混排归一化、书名匹配的容错与误命中防线、320 本书的坐标与书架结构关系、`hexu-library.glb` 的合并网格与预算、`smart-book.glb` 的铰链与部件命名、三份馆藏清单副本的一致性，以及语音适配器的生命周期（模拟浏览器识别事件，不等同于真人麦克风转录验收）。实际语音测试请在 Chrome/Edge 打开 localhost 后授权执行。界面测试应覆盖：唤醒、找书、向左拖动封面、显示简介、查看芯片、归还后重新找书。

保留依赖文件中的版权及许可头。Three.js 使用 MIT 许可；GSAP 3.12.5 的许可链接保留于 `public/vendor/gsap.min.js` 开头。地板与书柜的贴图来自 Poly Haven，授权为 **CC0（公有领域）**，可自由分发，无需署名；素材标识记录在 `tools/fetch-textures.mjs` 与 `blender/MATERIAL_REFERENCES.md`。
