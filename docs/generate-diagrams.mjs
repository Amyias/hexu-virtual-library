// Editable SVG diagrams for TECHNICAL_GUIDE.md. No external dependencies.
import fs from "node:fs";
import { drawArchitecture } from "./system-architecture.mjs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "diagrams");
fs.mkdirSync(dir, { recursive: true });
const esc = (s) =>
  String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
function diagram(name, title, subtitle, height, draw) {
  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="${height}" viewBox="0 0 1440 ${height}" role="img" aria-labelledby="title desc"><title id="title">${esc(title)}</title><desc id="desc">${esc(subtitle)}</desc><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 Z" fill="#526b69"/></marker></defs><style>text{font-family:'Microsoft YaHei','Noto Sans CJK SC',Arial,sans-serif;fill:#203b3b}.title{font-size:32px;font-weight:700}.sub{font-size:17px;fill:#627674}.lane{font-size:20px;font-weight:700}.node{font-size:19px;font-weight:700}.body{font-size:16px;fill:#4c6664}.label{font-size:15px;fill:#526b69;paint-order:stroke;stroke:#f5f7f4;stroke-width:7px;stroke-linejoin:round}</style><rect width="1440" height="${height}" fill="#f5f7f4"/>`,
  ];
  const text = (x, y, lines, cls = "body", gap = 25) =>
    parts.push(
      `<text x="${x}" y="${y}" class="${cls}">${lines.map((s, i) => `<tspan x="${x}" dy="${i ? gap : 0}">${esc(s)}</tspan>`).join("")}</text>`,
    );
  const lane = (x, y, w, h, title, color = "#e7eeea") => {
    parts.push(
      `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="20" fill="${color}" stroke="#cddbd5"/>`,
    );
    text(x + 24, y + 37, [title], "lane");
  };
  const box = (x, y, w, h, title, lines = [], color = "#fff") => {
    parts.push(
      `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="${color}" stroke="#b5cbc0" stroke-width="1.5"/>`,
    );
    text(x + 18, y + 31, [title], "node");
    text(x + 18, y + 58, lines);
  };
  const arrow = (points, label = "", x = 0, y = 0, dashed = false) => {
    parts.push(
      `<polyline points="${points.map((p) => p.join(",")).join(" ")}" fill="none" stroke="#526b69" stroke-width="2" ${dashed ? 'stroke-dasharray="7 6"' : ""} marker-end="url(#arrow)"/>`,
    );
    if (label) text(x, y, [label], "label");
  };
  text(40, 58, [title], "title");
  text(40, 94, [subtitle], "sub");
  draw({ text, lane, box, arrow });
  parts.push("</svg>");
  fs.writeFileSync(path.join(dir, name + ".svg"), parts.join("\n"));
}
drawArchitecture(diagram);
diagram(
  "voice-flow",
  "从一句话到一本书 · 语音与意图流程",
  "ASR 负责“听到什么”；规则与可选大模型负责“要做什么”；应用调度负责“如何执行”",
  1000,
  ({ text, lane, box, arrow }) => {
    lane(40, 135, 1360, 190, "01 / 音频转文本");
    box(65, 200, 270, 90, "启动语音感知", ["权限与本地启用偏好"]);
    box(395, 200, 270, 90, "探测 /asr/ready", ["就绪 → 录音上传后端"]);
    box(725, 200, 300, 90, "不可用 → Web Speech", ["continuous + interimResults"]);
    box(1080, 200, 295, 90, "统一转录入口", ["processText(text, …)"]);
    arrow([
      [335, 245],
      [395, 245],
    ]);
    arrow(
      [
        [665, 245],
        [725, 245],
      ],
      "否则",
      677,
      232,
    );
    arrow([
      [1025, 245],
      [1080, 245],
    ]);
    arrow(
      [
        [530, 290],
        [530, 310],
        [1228, 310],
        [1228, 290],
      ],
      "后端转录同样汇入",
      745,
      304,
    );
    lane(40, 355, 1360, 250, "02 / 唤醒门控与理解");
    box(65, 425, 285, 125, "唤醒 / 25 秒等待窗", [
      "仅叫“小和” → 气泡回应",
      "“有什么需求吗？”留在前台",
      "带需求或已唤醒 → 继续查询",
    ]);
    box(395, 425, 285, 125, "本地规则匹配", [
      "精确 > 片段 > 单字近似",
      "二字书名不做近似",
      "多个识别候选参与匹配",
    ]);
    box(725, 425, 300, 125, "可选 /understand", [
      "规则未命中且已配置时调用",
      "提供已入库书目（编号/书名/作者）",
      "解析 action / bookId / say",
    ]);
    box(1080, 425, 295, 125, "馆藏与正文承接", [
      "语义结果核对 bookId",
      "有效 → 实际馆藏对象",
      "未入库 → 检索正文并上架",
    ]);
    arrow([
      [1340, 290],
      [1340, 410],
      [207, 410],
      [207, 425],
    ]);
    arrow([
      [350, 487],
      [395, 487],
    ]);
    arrow(
      [
        [680, 487],
        [725, 487],
      ],
      "未命中",
      680,
      474,
      true,
    );
    arrow(
      [
        [1025, 487],
        [1080, 487],
      ],
      "",
      0,
      0,
      true,
    );
    arrow(
      [
        [538, 550],
        [538, 580],
        [1228, 580],
        [1228, 550],
      ],
      "本地命中直接执行",
      750,
      573,
    );
    lane(40, 640, 1360, 310, "03 / 动画执行与反馈");
    box(65, 715, 285, 110, "NAVIGATING", ["小和先到书架引导点", "高亮具体书籍实例"]);
    box(395, 715, 285, 110, "PRESENTING", ["隐藏架上目标实例", "完整书模型飞到相机前"]);
    box(725, 715, 300, 110, "READING", ["拖动 / 按钮 / 语音开合", "芯片 / 简介 / 本地正文翻页"]);
    box(1080, 715, 295, 110, "RETURNING → IDLE", [
      "合上、飞回、恢复实例",
      "小和回前台，释放阅读资源",
    ]);
    arrow([
      [1340, 550],
      [1340, 700],
      [207, 700],
      [207, 715],
    ]);
    arrow([
      [350, 770],
      [395, 770],
    ]);
    arrow([
      [680, 770],
      [725, 770],
    ]);
    arrow([
      [1025, 770],
      [1080, 770],
    ]);
    text(
      65,
      887,
      [
        "独立唤醒：只改变对话气泡和小和的唤醒动作，不触发导航。",
        "段式后端识别在句尾才返回文本；识别请求进行时暂停接收新的音频帧。",
      ],
      "body",
      27,
    );
  },
);
diagram(
  "asset-pipeline",
  "资产生产与运行加载 · 双书籍模板设计",
  "离线建模保留可编辑源文件；网页把静态环境、海量书脊和单本阅读模型分开加载",
  810,
  ({ text, lane, box, arrow }) => {
    lane(40, 135, 400, 610, "01 / 源数据与制作");
    lane(520, 135, 400, 610, "02 / 可分发资产", "#f0ece2");
    lane(1000, 135, 400, 610, "03 / 浏览器使用", "#e9edf4");
    box(65, 210, 350, 110, "Blender 环境制作", [
      "建筑、家具、植物、灯具",
      "UV / PBR / 集合与材质合并",
    ]);
    box(545, 210, 350, 110, "hexu-library.glb", ["Draco 几何压缩", "71 个网格 / 344,074 三角面"]);
    box(1025, 210, 350, 110, "GLTFLoader + DRACOLoader", [
      "本地解码器",
      "WebGL 场景 / 光照 / 阴影",
    ]);
    arrow(
      [
        [415, 265],
        [545, 265],
      ],
      "导出",
      460,
      251,
    );
    arrow(
      [
        [895, 265],
        [1025, 265],
      ],
      "加载",
      940,
      251,
    );
    box(65, 395, 350, 110, "书籍模型制作", [
      "shelf_books.py：书脊轻模板",
      "smart_books.py：完整芯片书",
    ]);
    box(545, 395, 350, 110, "两块 GLB 模板", [
      "shelf-book.glb：2 个部件",
      "smart-book.glb：封面铰链与芯片",
    ]);
    box(1025, 395, 350, 110, "两种细节层次", [
      "架上：已入库书 / 2 个实例池",
      "阅读：按需克隆完整模型",
    ]);
    arrow(
      [
        [415, 450],
        [545, 450],
      ],
      "导出",
      460,
      436,
    );
    arrow(
      [
        [895, 450],
        [1025, 450],
      ],
      "实例化",
      932,
      436,
    );
    box(65, 580, 350, 110, "唯一馆藏生成器", ["prepare-smart-books.mjs", "只生成空槽位，不含书目"]);
    box(545, 580, 350, 110, "唯一一份紧凑清单", [
      "public/models/book-inventory.json",
      "网页 / 本机服务 / Blender 同规则展开",
    ]);
    box(1025, 580, 350, 110, "编号与位置贯穿全链路", [
      "检索 / 坐标 / 芯片文字",
      "共同以 bookId 识别具体藏书",
    ]);
    arrow(
      [
        [415, 635],
        [545, 635],
      ],
      "生成",
      460,
      621,
    );
    arrow(
      [
        [895, 635],
        [1025, 635],
      ],
      "读取",
      940,
      621,
    );
    text(
      40,
      785,
      ["维护约束：改动坐标先生成清单，再在副本重建模型；核对清单与几何关系后再替换成品。"],
      "body",
    );
  },
);
console.log("Generated 3 editable SVG diagrams.");
