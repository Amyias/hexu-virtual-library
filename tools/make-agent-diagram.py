"""Draw 小和's agent loop as a draw.io file: docs/diagrams/agent-loop.drawio.

    python tools/make-agent-diagram.py

The layout follows the layered agent-loop sketch (user, runtime loop, tools, side branches)
and adds what the program really does around it: rules that answer before any model call,
retrieval beside memory, policy checks and the reader's own yes, tools run by the server or by
the page, and the two side branches (compaction during a conversation, memory consolidation
after it). Kept as a script so the picture changes with the code, not by hand.
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs" / "diagrams" / "agent-loop.drawio"

LAYER = ("rounded=1;whiteSpace=wrap;html=1;dashed=1;dashPattern=6 6;fillColor=#FAFAFA;strokeColor=#E1E4E8;"
         "align=left;verticalAlign=top;spacingLeft=12;spacingTop=5;fontSize=10;fontColor=#98A0AA;arcSize=2;")
COLOURS = {
    "plain": ("#FFFFFF", "#B9C0CB"), "stream": ("#E9F7F9", "#66C3CE"), "memory": ("#EEE8FA", "#A78BE0"),
    "context": ("#E4F4EA", "#74BE97"), "model": ("#FDF2DF", "#E3B471"), "route": ("#E4F4EE", "#6FBFB0"),
    "stop": ("#FCEAEE", "#E0808F"), "append": ("#E6F7EE", "#68C08C"), "rules": ("#EAF1FC", "#7BA3E0"),
    "side": ("#E6F6F2", "#6FC0A8"), "unused": ("#F5F5F5", "#C8C8C8"),
}
EDGE = {
    "main": "strokeColor=#3E9B6E;strokeWidth=1.2;",
    "cancel": "strokeColor=#D9534F;dashed=1;dashPattern=4 4;",
    "page": "strokeColor=#5B8DEF;dashed=1;dashPattern=4 4;",
    "memory": "strokeColor=#8E6FD8;dashed=1;dashPattern=1 3;",
}

cells = []


def layer(key, text, x, y, w, h):
    cells.append(f'<mxCell id="{key}" value="{escape(text)}" style="{LAYER}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')


def node(key, icon, title, lines, x, y, w, h, kind, dashed=False):
    fill, stroke = COLOURS[kind]
    body = (f"{icon} <b>{escape(title)}</b>" if icon else f"<b>{escape(title)}</b>") + "".join(
        f"<br><span style=\"font-size:8px;color:#5F6B7A\">{escape(line)}</span>" for line in lines)
    html = f'<div style="text-align:left">{body}</div>'
    style = (f"rounded=1;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;spacingLeft=6;spacingRight=4;"
             f"fontSize=10;arcSize=14;fillColor={fill};strokeColor={stroke};" + ("dashed=1;fontColor=#9AA0AA;" if dashed else ""))
    cells.append(f'<mxCell id="{key}" value="{escape(html, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')


def text(key, value, x, y, w, h, colour="#7A8598", size=9, bold=False):
    style = f"text;html=1;align=left;verticalAlign=middle;fontSize={size};fontColor={colour};" + ("fontStyle=1;" if bold else "")
    cells.append(f'<mxCell id="{key}" value="{escape(value)}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')


def edge(key, source, target, label, kind="main", exit_=None, entry=None, points=()):
    style = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endSize=4;fontSize=8;fontColor=#5A6472;" + EDGE[kind]
    if exit_:
        style += f"exitX={exit_[0]};exitY={exit_[1]};exitDx=0;exitDy=0;"
    if entry:
        style += f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
    way = "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in points)
    geometry = (f'<mxGeometry relative="1" as="geometry"><Array as="points">{way}</Array></mxGeometry>' if way
                else '<mxGeometry relative="1" as="geometry"/>')
    cells.append(f'<mxCell id="{key}" value="{escape(label)}" style="{style}" edge="1" parent="1" '
                 f'source="{source}" target="{target}">{geometry}</mxCell>')


# --- layers --------------------------------------------------------------------------------
layer("L1", "01 / 用户层  User", 40, 60, 1320, 100)
layer("L0", "00 / 本地分流  Rules first（不调用模型）", 40, 175, 1320, 80)
layer("L2", "02 / Agent Runtime 主循环", 40, 270, 1320, 175)
layer("L3", "03 / 工具层  Tool Layer", 40, 460, 1320, 175)
layer("L4", "04 / 旁路  Side Branches", 40, 650, 1320, 110)
text("T1", "输入 Intake", 120, 36, 120, 16, "#2E9E6B", 10, True)
text("T2", "推理 Reason", 560, 36, 120, 16, "#2E7BE0", 10, True)
text("T3", "行动与观察 Act · Stop", 1000, 36, 200, 16, "#E08A2E", 10, True)

# --- 01 user -------------------------------------------------------------------------------
node("in", "💬", "用户输入", ["语音：连续收听（VAD 断句 + 唤醒词）", "文字：对话面板"], 60, 88, 210, 56, "plain")
node("out", "☰", "流式输出", ["像素气泡逐字显示", "欣然逐句朗读"], 560, 88, 170, 56, "stream")
node("cancel", "✋", "用户中断", ["停止按钮 · 说「小和」打断播报"], 870, 88, 200, 56, "plain")
node("resp", "⏎", "返回响应", ["气泡 · 朗读 · 页面动作"], 1170, 88, 170, 56, "stream")

# --- 00 rules ------------------------------------------------------------------------------
node("rules", "⚑", "本地分流 decide()", ["唤醒 · 找书 · 阅读指令 · 记住 · 选书"], 290, 205, 230, 48, "rules")
node("direct", "▶", "直接执行", ["状态机取书、翻页、记住", "即时、免费"], 60, 205, 190, 48, "rules")

# --- 02 loop -------------------------------------------------------------------------------
node("memory", "{}", "记忆召回", ["事实 · 推测 · 印象 · 摘要", "按相关度取用，≤ 520 字"], 60, 300, 200, 56, "memory")
node("rag", "❡", "原文检索 · 眼前这一页", ["FTS5 + 句向量 RRF，防剧透", "追问带上上一句；问「这段」附本页"], 60, 368, 200, 64, "memory")
node("build", "", "构建上下文 Build Context", ["人格 system · 前情摘要", "最近 3–6 轮原文", "工具清单：按状态每轮重算", "tools/llm_chat.py"], 300, 300, 210, 90, "context")
node("llm", "✦", "LLM 调用", ["流式 Chat Completions", "可配置的模型服务"], 560, 305, 170, 66, "model")
node("routeout", "⇄", "输出判定", ["有没有 tool_calls?"], 770, 305, 150, 66, "route")
node("stop", "⏹", "停止条件 Stop Check", ["完成 · 联网至多 2 轮（末轮强制作答）", "每轮界面动作 ≤ 3 · 60 秒超时", "回复超长 · 出错"], 970, 295, 230, 86, "stop")

# --- 03 tools ------------------------------------------------------------------------------
node("policy", "⚿", "政策审批 Policy", ["按状态的白名单", "参数逐项核对 · 次数上限", "tools/app_actions.py"], 560, 490, 170, 66, "stop")
node("server", "⚙", "服务端执行", ["查书 · 书签 · 推荐", "联网搜索 / 抓取"], 780, 480, 170, 58, "model")
node("page", "⚙", "页面执行（动作事件）", ["天空 · 取书 · 翻章 · 音乐 · 定位 · 字号", "页面再核对；取书后的翻章等书到手"], 780, 550, 240, 70, "model")
node("append", "＋", "追加结果 Append", ["工具结果 / 拒绝原因", "回给模型"], 1070, 485, 160, 62, "append")
node("consent", "✔", "读者确认（循环外）", ["下载：说「要」才下载", "30 秒内有效"], 1070, 560, 160, 62, "stop")

# --- 04 side ------------------------------------------------------------------------------
node("compact", "⇩", "上下文压缩 Compaction", ["超 6 轮 / 24000 字时", "较早几轮 → 前情摘要（/chat/compact）"], 300, 680, 240, 62, "side")
node("consolidate", "✎", "记忆整理", ["对话安静 3 分钟后，同一次调用写：", "摘要 · 重要度 · 推测 · 读者印象"], 600, 680, 250, 62, "side")
node("sub", "✧", "子智能体 Subagent", ["未采用：每轮至多 3 个小工具，", "且多有先后，无需另开循环"], 1070, 680, 210, 62, "unused", dashed=True)

# --- edges ---------------------------------------------------------------------------------
edge("e1", "in", "rules", "输入", exit_=(1, 0.5), entry=(0.5, 0), points=[(405, 116)])
edge("e2", "rules", "direct", "命中规则", exit_=(0, 0.5), entry=(1, 0.5))
edge("e3", "rules", "build", "对话 · 长尾", exit_=(0.5, 1), entry=(0.5, 0))
edge("e4", "memory", "build", "召回", "memory", entry=(0, 0.3))
edge("e5", "rag", "build", "片段", "memory", entry=(0, 0.8))
edge("e6", "build", "llm", "prompt", entry=(0, 0.5))
edge("e7", "llm", "out", "stream", "page", exit_=(0.5, 0), entry=(0.5, 1))
edge("e8", "llm", "routeout", "输出")
edge("e9", "routeout", "stop", "无 tool_calls")
edge("e10", "stop", "resp", "结束", exit_=(0.75, 0), entry=(0.5, 1))
edge("e11", "cancel", "stop", "取消", "cancel", exit_=(0.5, 1), entry=(0.3, 0))
edge("e12", "routeout", "policy", "tool_calls", exit_=(0.5, 1), entry=(0.5, 0), points=[(845, 470), (645, 470)])
edge("e13", "policy", "server", "允许", entry=(0, 0.5))
edge("e14", "policy", "page", "允许", "page", exit_=(1, 0.8), entry=(0, 0.5))
edge("e15", "server", "append", "结果", entry=(0, 0.3))
edge("e16", "page", "append", "已交给页面", "page", exit_=(1, 0.3), entry=(0, 0.8))
edge("e17", "page", "consent", "下载提议", "cancel", exit_=(1, 0.8), entry=(0, 0.7))
edge("e18", "policy", "append", "拒绝 → 错误结果", "cancel", exit_=(0.5, 1), entry=(0.15, 1), points=[(645, 628), (1094, 628)])
edge("e19", "append", "build", "未达上限：下一轮", exit_=(0.7, 1), entry=(0.5, 1), points=[(1182, 642), (405, 642)])
edge("e20", "build", "compact", "超出预算", "memory", exit_=(0.3, 1), entry=(0.3, 0))
edge("e21", "compact", "build", "前情摘要", "memory", exit_=(0.7, 0), entry=(0.7, 1))
edge("e22", "resp", "consolidate", "对话结束（安静 3 分钟）", "memory", exit_=(0.5, 1), entry=(0.5, 1), points=[(1255, 170), (1350, 170), (1350, 752), (725, 752)])
edge("e23", "consolidate", "memory", "写入记忆", "memory", exit_=(0, 0.5), entry=(0, 0.5), points=[(570, 711), (570, 770), (48, 770), (48, 328)])

# --- legend --------------------------------------------------------------------------------
text("legend", "图例：绿实线 主流程 · 蓝虚线 流式 / 交给页面 · 红虚线 中断、拒绝与读者确认 · 紫点线 记忆与压缩 · 灰虚框 未采用",
     40, 780, 900, 18, "#444444", 10)

xml = ('<mxfile host="app.diagrams.net" type="device">'
       '<diagram id="xiaohe-agent-loop" name="小和 Agent 主循环（2.8）">'
       '<mxGraphModel dx="1400" dy="820" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
       'fold="1" page="1" pageScale="1" pageWidth="1400" pageHeight="820" math="0" shadow="0"><root>'
       '<mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>\n")
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(xml, encoding="utf-8")
print(OUT, len(cells), "cells")
