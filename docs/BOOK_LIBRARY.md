# 本地正文书库与小说阅读

书架原有的数据是书名、作者、位置与简介，不包含小说全文。现在正文通过本机服务下载或导入，保存到独立书库；网页重新打开时读取书库，把书目绑定到现有编号样书。模型文件与芯片编号不需要重新生成。

## 如何使用

1. 启动最新版源码服务 `npm start`，或使用重新打包后的本机程序。源码模式的书库服务需要 Python 3.10+，只使用标准库，无需安装爬虫或数据库依赖。若 Python 不在 PATH，可设置 `HEXU_PYTHON` 指向解释器，再启动服务。
2. 点击一次「启动语音感知」，允许麦克风。说「小和」，小和仅回答「有什么需求吗？」；接着说「帮我找狂人日记」。也可以直接说「小和，帮我找狂人日记」。文字搜索框走相同的找书逻辑。
3. 已有本地正文时直接取书，不访问在线书源。未入库的书名会进入在线正文检索；精确结果唯一时自动下载，多个候选时在面板选择「下载并上架」。下载进度会显示当前章节，支持取消。
4. 正文完整保存后，小和飞到绑定的书架位置并取出书本。向左拖动封面，或点击「翻开书页」，进入正文阅读。也可点击「阅读正文」。
5. 用上一页、下一页、左右方向键或水平滑动翻页；目录可直接跳章，A−/A＋调整字号。阅读位置按章节与字符偏移保存，重新打开会恢复。
6. 点击「返回 3D 书本」查看芯片，随后「放回书架」。小和回到前台待命。语音也支持「小和，下一页」「小和，上一页」「小和，读正文」「小和，看芯片」「小和，放回书架」。

原有 12 本演示馆藏仍保留简介演示，首页的探索按钮可直接体验。语音或文字明确指定它们的书名时，也会先检索正文；演示书上的「查找正文」提供同样入口。能否下载取决于书源是否实际提供该书，找不到时会显示结果，不会生成假的小说正文。

## 存储与备份

Windows 默认位置为 `%APPDATA%\hexu-library\books`；其他系统默认 `~/.local/share/hexu-library/books`。界面的「正文书库 → 书库位置」显示实际路径。可用环境变量 `HEXU_BOOK_LIBRARY_DIR` 指定其他目录。

目录内包含：

| 文件 | 内容 |
| --- | --- |
| `library.sqlite` | 书目、完整章节、来源、书源规则与阅读进度 |
| `<书库ID>.txt` | UTF-8 全文副本，便于直接打开和备份 |

书库 ID 由来源与该来源的书籍标识生成，重复下载不会重复上架；书架槽位写入数据库，重启后位置稳定。网页把槽位映射到现有样书，保留该位置的 HX 芯片编号、模型实例与坐标。现有演示书目不被覆盖，新增书目优先安排到文学书架的空闲样书位置，再使用其他样书。

关闭程序后复制整个书库目录即可备份。程序更新与 Git 源码提交不包含用户书库；搬到另一台电脑时另行复制它。阅读已下载的正文不需要外网，但本机 HTTP 服务仍须运行。浏览器的语音识别是否能离线使用取决于所选识别通道。

## 书源与文件导入

内置 [中文维基文库](https://zh.wikisource.org/)，通过 MediaWiki API 获取真实文本，保留作者、来源链接、许可说明和修订号。目录指向同书子页面时逐章下载；全文在单页时按「第几章／回」或 `Chapter N` 标题拆分。个别文献的特殊目录格式可能需要选择具体分卷或另一个版本。

「正文书库 → 书源管理与导入」提供 [源仓库](https://www.yckceo.com/yuedu/shuyuan/index.html) 入口。先下载 JSON 文件再导入；面板分别列出成功和拒绝的书源及原因。支持本项目的静态 CSS 格式，以及 Legado 3.x 中使用同样 CSS 语法的声明式子集，**不等同于完整兼容阅读 App 的所有书源**。

支持标签、`.class`、`#id` 与空格分隔的后代选择器；字段可用 `@text`、`@href`、`@src`、`@title`，允许 `@css:` 前缀。支持 GET 搜索地址的 `{{key}}`、`{query}`、`{{page}}`（第一页）。一本书的详情页须直接包含章节目录，章节页须直接包含正文。

以下为格式示例，需要改成实际站点的地址与选择器，不是可直接下载的书源：

```json
{
  "name": "My free-text source",
  "base_url": "https://example.com",
  "search_url": "/search?q={{key}}",
  "search": {
    "items": ".book-result",
    "title": "a.title@text",
    "url": "a.title@href",
    "author": ".author@text"
  },
  "toc": {
    "items": ".chapter-list a",
    "title": "@text",
    "url": "@href"
  },
  "content": {"body": "#chapter-content@text"},
  "license": "Publicly available free text; see source page"
}
```

暂不支持 JavaScript、XPath、JSONPath、Legado 的 `class.xxx@tag.a` 链式语法、POST 搜索、登录、验证码、跨域章节、正文的「下一页」拼接与图像/PDF 转文字。不会执行导入 JSON 中的代码，也不会绕过站点访问控制。自定义书源仅访问其同域公开 HTTP(S) 地址；本机、内网和保留地址被拒绝。代理返回保留地址的 DNS 环境也可能导致该书源被拒绝。

「导入 TXT / EPUB」支持 UTF-8、带 BOM 的 UTF-16 与 GB18030 TXT，以及无加密的 EPUB。EPUB 按 spine 顺序读取，并将 HTML 转为纯文本，脚本不会进入页面。导入的是本机实际文件内容，不会发送给大语言模型。

当前限制：单次导入文件 8 MiB，EPUB 解压后总量 32 MiB；在线单页响应 4 MiB，一次下载最多 500 个章节页，整书最多 1000 万字符；最多两个同时下载任务。所有来源检索默认包括前五个自定义源和维基文库，其他书源可通过下拉框单独选择。取消会在当前网络请求结束后生效；失败或取消的任务不会作为完整书籍入库，重试从头下载。

## 模块与接口

```text
ASR / 文字输入
       ↓
src/app.js → 本地书目匹配 → 3D 取书与封面开合
       ↓ 未入库                     ↓
src/reader/library.js       src/reader/novel.js
       ↓ 搜索 / 下载 / 导入          ↓ 章节 / 分页 / 进度
                  /library/*
                       ↓
              tools/book_library.py
                  ↙             ↘
       tools/book_sources.py    SQLite + UTF-8 TXT
          ↙          ↘
  MediaWiki API   自定义静态 CSS 书源
```

`npm start` 的 Node 服务按需启动 `tools/library-service.py` 子进程并代理 `/library/*`；Python 本机程序与服务器则直接复用 `book_library`，两条运行路径使用相同的数据库与下载逻辑。正文显示使用 `textContent`，不会把远端 HTML 当作可执行页面。

| 接口 | 用途 |
| --- | --- |
| `GET /library/ready` | 探测书库服务与实际存储路径 |
| `GET /library/books` | 已入库目录 |
| `GET /library/books/<id>` | 全部章节与保存的阅读位置 |
| `GET /library/search?q=...&source=all` | 本地优先、在线候选与分来源错误 |
| `GET /library/sources` | 可用书源 |
| `POST /library/download` | 根据搜索候选建立异步任务 |
| `GET /library/jobs/<id>` | 下载状态和进度 |
| `POST /library/jobs/<id>` | 请求取消任务 |
| `POST /library/import` | 导入文件名与 Base64 文件内容 |
| `POST /library/sources` | 导入书源 JSON 对象或数组 |
| `POST /library/progress/<id>` | 保存 `chapter` 和 `offset` |

分页在当前窗口内测量真实文字高度，不使用固定字符数截断或简介占位。翻页的下一页起点等于上一页结束偏移，调整字号与窗口尺寸后重新排版；字符偏移让进度不依赖页码变化。

## 验证

```powershell
npm test
python -m unittest discover -s tests -p "test_*.py"
```

后端测试覆盖持久化、章节与进度恢复、重复入库、EPUB 顺序、脚本剔除、静态书源下载、取消和失败不入库、网络不可用时本地别名命中。界面改动还需在浏览器完成加载 → 找书 → 拖开封面 → 正文翻页 → 查看芯片 → 归还 → 待命，并检查字号、移动端排版与重新打开后的阅读进度。
