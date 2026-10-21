# 文档导出与迁移

编辑源文档 `docs/TECHNICAL_GUIDE.md` 后重新导出，避免 HTML、Markdown 分享版和压缩包内容不同步。

## 使用成品

- 只想移动一个文件：复制 `docs/portable/TECHNICAL_GUIDE.html`。图表与样式内嵌，浏览器可离线阅读。
- 需要 Markdown：完整解压 `docs/TECHNICAL_GUIDE_PORTABLE.zip`，保持 `TECHNICAL_GUIDE.md` 与 `diagrams/` 在同一目录。正文配图使用 PNG，SVG 原图保留。
- 源文档里的 `../src/` 等链接在导出时转换为 GitHub 仓库 `master` 分支的链接，避免搬走后错误指向本地文件。私有仓库的源码链接需要登录与网络。

普通 Markdown 阅读器并不统一支持内嵌 SVG、HTML 或 data URI。因此不依赖这些特性来实现单文件 Markdown；单文件阅读由 HTML 版提供。

## 重新生成

Node.js 需要可解析 `marked`（导出器使用 17.0.5；仅构建时使用，成品没有 JavaScript、CDN 或字体下载）。项目运行不需要安装此依赖。

```powershell
npm install --no-save --package-lock=false marked@17.0.5
node docs/export-guide.mjs
npm test
```

如果本机已有工具依赖目录，可通过 `NODE_PATH` 指向含 `marked` 的 `node_modules` 后运行导出脚本，无需重复安装。

修改 SVG 后先运行 `node docs/generate-diagrams.mjs`，并用 SVG 渲染工具更新对应 PNG 预览，再导出。导出器会生成三张 SVG 内嵌的 HTML、含 PNG 配图的 Markdown、六张图文件和 ZIP；图表 ID 按文件名隔离，避免同页箭头与可访问性标题冲突。

系统架构图的布局在 `docs/system-architecture.mjs`，由生成器调用。更新架构时同步图内的源码基线、技术文档说明和 PNG，保留 SVG 自包含特性，不引用外部图片、脚本或字体文件。

## 验证迁移

1. 只复制 HTML 到项目外的新目录，用浏览器打开；断网也应显示正文和三张图。
2. 将 ZIP 解压到另一个空目录，验证 Markdown 的三个 PNG 路径和所有 SVG/PNG 下载链接存在。
3. 检查 ZIP 解压内容与 `docs/portable/` 一致，再运行 `npm test`。文档导出不修改场景和模型。
