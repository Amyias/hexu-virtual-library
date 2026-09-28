# 服务器部署（服务端语音识别）

本文件说明如何把项目部署到服务器，并用服务器本地的语音模型做识别。

**静态模式不受影响。** 用 `npm start` 本地打开时行为与从前完全一致——浏览器探测不到后端就沿用 Web Speech API。

## 为什么需要这个模式

浏览器自带的 Web Speech API **硬绑定到浏览器厂商的云服务，端点不可自定义**（Chrome 用的是 `speech.googleapis.com`）。在连不上该服务的网络里，识别器会启动、界面显示「监听中」，然后**一个结果都不返回**。

所以修法不是把站点放到服务器上——**那没用**，识别是在你的浏览器里发起、由你的机器去连那个云服务的。真正起作用的是：**浏览器录音 → 传到服务器 → 服务器用本地模型识别**。

## 当前部署（香港节点）

| 项 | 值 |
| --- | --- |
| 主机 | `64.90.2.91`（Ubuntu 24.04，4 vCPU / 8 GB） |
| 站点目录 | `/opt/hexu-library` |
| Python 环境 | `/opt/hexu-library/venv`（sherpa-onnx + numpy，独立于其它项目） |
| 识别模型 | `/opt/hiyori-voice/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17`（**只读引用，未复制**） |
| 服务 | `hexu-library.service` |
| 监听 | `127.0.0.1:8090`（仅本机，不对公网开放） |
| 访问方式 | SSH 隧道 |

### ⚠️ 同一台机器上的另一个项目

服务器上另有 `/opt/hiyori-assistant` 与 `/opt/hiyori-voice`——那是一个**独立的个人助手项目**（含它自己的语音模型与 venv），以及 `/root` 下它的一整套部署脚本。语音模型正是从那里只读借用的。

**不要改动、不要重启、不要升级那两项，也不要删除。** 本项目的部署与它零交集：不同目录、不同端口、不同 venv、不同服务名。

## 访问

隧道：

```bash
ssh -i ~/.ssh/rainyun-rcs-Snowy_Brew.pem -L 8090:127.0.0.1:8090 root@64.90.2.91
```

保持这个终端开着，浏览器打开 **http://localhost:8090**。

必须经隧道（`localhost`）访问的原因：`http://64.90.2.91:8090` 这样的公网明文地址**不是安全上下文，浏览器不给麦克风权限**；而 `localhost` 被浏览器视为安全上下文，麦克风可用。

## 架构

`tools/asr-server.py` 一个进程同时做两件事：

| 路由 | 作用 |
| --- | --- |
| `GET /` 与静态文件 | 提供站点，路径解析后必须落在站点根内，否则 403 |
| `GET /asr/ready` | 返回模型是否就绪；前端探测它决定用哪条识别通道 |
| `POST /asr` | 收 16 kHz 单声道 WAV，返回 `{"text": ...}` |

**服务端不发出任何对外请求**，因此没有 SSRF 面；页面与接口同源同端口，所以不需要 CORS，也只需要开一条隧道。

识别核心：

```python
sherpa_onnx.OfflineRecognizer.from_sense_voice(
    model=..., tokens=..., num_threads=2, use_itn=True, language="zh")
stream = recognizer.create_stream()
stream.accept_waveform(16000, samples)      # float32，[-1, 1]
recognizer.decode_stream(stream)
stream.result.text
```

模型单例复用、解码加锁串行。输入约束与静音门限：0.25–45 秒、1.5 MB 上限、RMS < 0.0015 直接返回空文本（不浪费一次解码）。

## 前端如何选择通道

`src/voice/server-asr.js` 在启动时 `GET /asr/ready`：

- **就绪** → 用服务端通道：`getUserMedia` 录音 → 能量断句（检测到说话后静音约 0.7 秒判为一句）→ 编成 WAV → `POST /asr` → 文本交给**同一个** `processText` 派发器
- **未就绪** → 完全沿用原有 Web Speech 路径

探测是异步的，**Web Speech 的装配仍是同步的**，所以静态部署与既有测试路径一字未变。

### 免点击自动收听

用户点过「启动语音感知」之后，选择写入 `localStorage`（键 `hexu.voice.enabled`）。此后每次打开页面都自动开始收听，无需再点。

之所以不能做到**零**点击：浏览器的麦克风授权本身必须由用户手势触发，任何页面都绕不过。但**授权一旦持久化，无手势的新文档也能自行开麦**——这一点已实测确认：

| 在全新加载、未做任何交互的文档里 | 结果 |
| --- | --- |
| `navigator.permissions.query({name:"microphone"})` | `granted` |
| `getUserMedia({audio:true})` | 成功，无需手势 |
| `new AudioContext({sampleRate:16000})` | 初始即 `running` |

所以实现是：启动时若记住过选择就直接开麦；若浏览器仍要手势，则挂一次性监听，用户碰一下页面任意处即开始。用户显式关闭语音会清除该偏好，下次不再自动开。

## 已知取舍

- **没有 interim 结果**。段式识别只能拿到整句，所以「话说到一半就亮起」变成「说完才亮起」。唤醒仍然发生——`app.js` 在 final 文本里检测唤醒词，只是时机晚到句尾。
- **页面切到后台会暂停录音**，与 Web Speech 通道行为一致，避免转录未被要求聆听的对话。
- **首次识别较慢**（约 2 秒，含模型载入），之后每句约 0.3–0.5 秒。
- 内存常驻约 300 MB。

## 更新部署

站点文件改动后同步过去（排除本地开发用的目录）：

```bash
cd /path/to/智能虚拟图书馆
tar czf - --exclude=node_modules --exclude=.git --exclude=.mimosa --exclude=.zcode \
  --exclude=__pycache__ --exclude='*.blend1' . \
  | ssh -i ~/.ssh/rainyun-rcs-Snowy_Brew.pem root@64.90.2.91 \
      'tar xzf - -C /opt/hexu-library && systemctl restart hexu-library'
```

只改了前端资源时不必重启服务（静态文件每次请求现读）。

## 验证

```bash
# 模型就绪
curl -s http://127.0.0.1:8090/asr/ready

# 用模型自带的样例音频验识别（服务器上执行）
M=/opt/hiyori-voice/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17
curl -s -X POST --data-binary @$M/test_wavs/zh.wav http://127.0.0.1:8090/asr
# 期望：{"text": "开饭时间早上9点至下午5点。", ...}

# 服务状态
systemctl status hexu-library
journalctl -u hexu-library -n 20 --no-pager
```

## 安全约束

- 服务只监听 `127.0.0.1`，不暴露公网；访问必须经 SSH 隧道（密钥认证）。
- 单元文件里只有路径与环境变量，**没有任何凭据值**。
- SSH 密钥只在建立连接时以 `-i` 使用，不读取、不打印、不复制、不写入仓库。
- 站点目录对服务进程只读即可；服务不写任何文件。
