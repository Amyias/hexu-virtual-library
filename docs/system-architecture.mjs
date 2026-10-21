// Architecture snapshot verified against master b916856 (2026-10-21).
// Keep the SVG self-contained: no external images, fonts, scripts or stylesheets.
export function drawArchitecture(diagram) {
  diagram(
    "architecture",
    "和序图书馆 · 系统架构",
    "2026-10-21 · 源码基线 b916856 · 实线：主要调用与数据流；虚线：构建与分发路径",
    1830,
    ({ text, lane, box, arrow }) => {
      lane(40, 135, 1360, 175, "01 / 运行入口 · 共用同一套网页应用");
      box(65, 195, 625, 90, "Windows 本机程序", [
        "pywebview + WebView2 · 默认最大化 · 内嵌设置与窗口控制",
      ]);
      box(720, 195, 655, 90, "Chrome / Edge 浏览器", [
        "HTML5 / CSS3 / ES Modules · 开发服务由 Node.js 提供",
      ]);
      arrow([
        [377, 285],
        [377, 340],
        [720, 340],
        [720, 380],
      ]);
      arrow([
        [1047, 285],
        [1047, 340],
        [720, 340],
      ]);

      lane(40, 380, 1360, 360, "02 / 前端应用 · src/main.js → src/app.js");
      box(65, 450, 400, 145, "输入与意图识别", [
        "语音感知 /「和 · 对话」/ 鼠标键盘",
        "speech.js → assistant.js / dialogue.js",
        "唤醒词容错；先区分聊天与找书",
        "仅匹配已入库书目的编号与位置",
      ]);
      box(500, 450, 400, 145, "调度与状态机", [
        "phases.js + journey.js",
        "待命 → 导航 → 展示 → 阅读 → 归还",
        "自由问答与阅读指令分别执行",
        "取还动画由 GSAP 串行编排",
      ]);
      box(935, 450, 440, 145, "3D 场景与阅读", [
        "Three.js / WebGL · GLB / Draco",
        "实例化书脊 / 翻盖书本 / 芯片查看",
        "真实正文分页 / 阅读进度 / 阅读音乐",
        "日月随时间切换 / 日光与灯光阴影",
      ]);
      arrow([
        [465, 520],
        [500, 520],
      ]);
      arrow([
        [900, 520],
        [935, 520],
      ]);
      arrow([
        [700, 595],
        [700, 635],
      ]);
      box(65, 635, 1310, 80, "统一反馈 · 所有回答回到小和身边", [
        "像素气泡逐字显示 / 可滚动长回答 / 来源链接 / 气泡与打字音效 / 本机语音播报，缺模型时退回系统语音",
      ]);
      arrow(
        [
          [720, 740],
          [720, 810],
        ],
        "同源 HTTP JSON / WAV · 就绪探测后启用服务；浏览器不持有模型 API 密钥",
        395,
        781,
      );

      lane(40, 810, 1360, 300, "03 / 本机 Python 服务 · tools/asr-server.py", "#e9edf4");
      box(65, 875, 305, 170, "听见与说话", [
        "/asr · SenseVoice / sherpa-onnx",
        "16 kHz 单声道 WAV → 文本",
        "/tts · PrimeTTS v2.1 / ONNX",
        "台湾女声「欣然」→ WAV",
        "两种模型均在本机 CPU 推理",
      ]);
      box(395, 875, 305, 170, "模型代理与联网工具", [
        "/chat · 自由问答与多轮对话",
        "/understand · 可选语义解析",
        "llm_chat.py + web_tools.py",
        "DeepSeek 默认关闭思考模式",
        "按需调用 Search / Fetch",
      ]);
      box(725, 875, 305, 170, "正文书库与书源", [
        "/library/* · book_library.py",
        "检索 / 下载 / 导入 TXT、EPUB",
        "CSS / XPath / JSONPath / JS",
        "真实书入库 → 固定槽位上架",
        "书目、章节、进度持久化",
      ]);
      box(1055, 875, 320, 170, "设置与桌面维护", [
        "/settings/* · /update/*",
        "window_host / window_chrome",
        "updater.py + 更新助手",
        "检查版本 → 校验 → 安装重启",
        "设置与更新接口限制回环访问",
      ]);
      text(65, 1083, [
        "开发模式：tools/serve.mjs 将服务请求代理到 Python sidecar；本机版由 Python 同时提供站点与 API。",
      ]);

      arrow([
        [380, 1110],
        [380, 1170],
      ]);
      arrow([
        [1060, 1110],
        [1060, 1170],
      ]);
      lane(40, 1170, 660, 250, "04 / 本机数据 · 离线资源与私有配置", "#e7eeea");
      box(65, 1230, 610, 175, "用户数据与模型", [
        "SQLite：书目 / 章节 / 书源 / 阅读进度；TXT 正文副本",
        "book-inventory.json：11,360 个空槽位，只上架真实书籍",
        "SenseVoice 识别模型 / PrimeTTS 播报模型",
        "API 设置由用户保存在仓库外；对话上下文在页面内存",
        "程序更新保留用户书库、配置与模型",
      ]);
      lane(740, 1170, 660, 250, "05 / 外部服务 · 按配置与请求访问", "#f0ece2");
      box(765, 1230, 610, 175, "模型 API、书源与版本服务", [
        "DeepSeek 或 Chat Completions 兼容服务：文本 → 回答",
        "DeepSeek Search / Fetch：检索网页与抓取正文作为回答依据",
        "小说书源：万卷书屋 / 天涯书库 / 书包网及导入的书源",
        "GitHub Releases：程序与语音识别模型发行附件",
        "浏览器 Web Speech：本机 ASR 未就绪时的识别备选",
      ]);

      lane(40, 1480, 1360, 245, "06 / 资产制作与发行 · 开发期生成，运行期读取", "#f0ece2");
      box(65, 1545, 400, 135, "Blender 5.2 + Python", [
        "环境 / 植物 / 统一书本 / 像素小和",
        "程序化建模、定点替换与不变量校验",
        "光照配置 / 烘焙接触遮蔽 / 日月模型",
      ]);
      box(500, 1545, 400, 135, "public/ 离线站点资产", [
        "GLB / 贴图 / 物理槽位清单",
        "本地 Three.js、GSAP、解码器、字体",
        "public/models + public/vendor",
      ]);
      box(935, 1545, 440, 135, "构建、发布与校验", [
        "PyInstaller → Windows 程序",
        "release.mjs → GitHub Release 草稿",
        "程序包 + 识别模型包，校验后发布",
      ]);
      arrow(
        [
          [465, 1610],
          [500, 1610],
        ],
        "",
        0,
        0,
        true,
      );
      arrow(
        [
          [900, 1610],
          [935, 1610],
        ],
        "",
        0,
        0,
        true,
      );
      text(65, 1758, [
        "能力边界：静态站点可展示场景；正文书库依赖 Python；自由问答需配置模型 API；真人语音需麦克风授权。",
        "此图可单独移动并离线打开：全部图形、文字与样式内嵌 SVG，不依赖 CDN、图片文件或字体下载。",
      ]);
    },
  );
}
