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

（唯一例外是下面可选的语义解析层：启用后，仅在本地规则理解不了时向你所配置的模型服务发出请求。）

## 可选的语义解析层

本地规则匹配的是书名与别名，快、免费、离线可用，但读不懂「霍金写的那本」。配一个大语言模型之后，这类说法交给它判断要哪一本。

**默认关闭。** 没有配置密钥时 `/understand/ready` 返回 `ready:false`，页面继续只用本地规则——功能不退化，只是少了理解长尾的能力。

### 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HEXU_LLM_API_KEY` | 无 | 缺省即关闭整个语义层 |
| `HEXU_LLM_BASE_URL` | `https://api.deepseek.com` | 仅接受 https，且拒绝回环/私有/保留地址 |
| `HEXU_LLM_MODEL` | `deepseek-flash` | 换 `deepseek-v4-pro` 可提质，贵 50～70 倍 |
| `HEXU_LLM_TIMEOUT` | `12` | 秒；超时即退回本地提示 |

密钥放在**仓库之外**、root-only 的文件里，由 systemd 注入：

```bash
install -d -m 700 /etc/hexu-library
install -m 600 /dev/null /etc/hexu-library/llm.env
cat > /etc/hexu-library/llm.env <<'EOF'
HEXU_LLM_API_KEY=<在下面填入你自己的 key>
HEXU_LLM_BASE_URL=https://api.deepseek.com
HEXU_LLM_MODEL=deepseek-flash
EOF
chmod 600 /etc/hexu-library/llm.env
```

然后在 `hexu-library.service` 的 `[Service]` 里加一行 `EnvironmentFile=/etc/hexu-library/llm.env`，`systemctl daemon-reload && systemctl restart hexu-library`。

服务**在每次请求时**从环境变量读取密钥，不缓存、不落盘、不打印；单元文件里只有路径。

### 模型调用方式

按 **OpenAI 兼容格式**，所以换厂商只改 `HEXU_LLM_BASE_URL` 与 `HEXU_LLM_MODEL`，代码不动。当前针对 DeepSeek V4 代际的三个细节：

- `thinking` 默认为 `enabled`，本服务显式传 `{"type":"disabled"}`——意图分类是受限任务，思考只增加延迟与费用，而且**思考模式下 `temperature` 会被静默忽略**，那正是维持输出稳定的手段。
- `response_format: {"type":"json_object"}` 可用，但文档要求提示词自己写明输出 JSON，提示词里写死了。
- 输出里返回的 `bookId` **一律在服务端核对是否存在于馆藏清单**，模型编造的编号直接判为 `none`——绝不信任模型给出的目标对象。

提示词只列**12 本有正式书名的书**（加一句说明其余 308 本只有编号、按编号查找由本地规则处理）。这很关键：编号样书的书名就是它的编号，列出来要几千 token 却教不会模型任何东西，而按编号找书本地规则本来就能做。所以提示词只有约 930 字符。

### 费用

每次调用约 950 输入 token（固定的提示词前缀，会被服务商的自动前缀缓存命中）+ 约 40 输出 token。按 DeepSeek 官方价（`deepseek-flash`，缓存命中 $0.003/M、未命中 $0.15/M、输出 $0.6/M）：**缓存命中时约 $0.00005/次**，即使用户每次都未命中也不到 $0.001。按每天几十次估计，每月远低于一元。

### 隐私

启用后，**转写文本与那份书单会发送到 DeepSeek**。音频始终不出服务器（识别在本地完成）。这一条也写在界面帮助里，不让用户意外。

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
tar czf - index.html src public tools DEPLOY.md README.md DEVELOPMENT.md AGENTS.md \
  | ssh -i ~/.ssh/rainyun-rcs-Snowy_Brew.pem root@64.90.2.91 \
      'tar xzf - -C /opt/hexu-library && systemctl restart hexu-library'
```

**只打包站点需要的路径**，不要用 `tar .` 整目录覆盖：服务器上的 `/opt/hexu-library/models/`（230 MB 识别模型）与 `/opt/hexu-library/venv/` 是服务器侧独有的，虽然 `tar` 解包只增不改不会删掉它们，但限定范围更稳妥。

同步后要重跑预压缩（见下）。只改了前端资源时不必重启服务（静态文件每次请求现读）。

## 加载速度

服务器上行只有 10 Mbps，模型体积直接决定等待时间。三层措施：

### 1. 几何用 Draco 压缩

`build_library.py` 导出时启用 `KHR_draco_mesh_compression`（量化 位置 14 / 法线 10 / UV 12 位）。几何从 12.97 MiB 压到 1.49 MiB，**零视觉损失**——比删减几何正确，因为那些面是植物的叶片。解码器 vendored 在 `public/vendor/draco/`，不经 CDN。

### 2. 预压缩（部署步骤）

`tools/asr-server.py` 会优先返回同名的 `.gz`（当客户端接受 gzip 且 `.gz` 不比原文件旧），**它自己只读不写**，压缩由部署时完成：

```bash
find /opt/hexu-library -type f \( -name '*.glb' -o -name '*.js' -o -name '*.css' \
  -o -name '*.html' -o -name '*.json' -o -name '*.jpg' -o -name '*.png' -o -name '*.wasm' \) \
  -size +32k ! -name '*.gz' -print0 | xargs -0 -r gzip -9 -k -f
```

改过文件后要重跑，否则旧 `.gz` 会被判为过期而跳过（服务端会比较两者的修改时间）。

### 3. 条件请求（304）

响应带 `ETag` 与 `Cache-Control: no-cache`：浏览器会重新校验，未改动时得到 **304、0 字节**，已下载的 6 MB 不再重传。这一层对"每天打开"的体验影响最大。

### 实测（经隧道，上行 10 Mbps）

| 场景 | 原始 | 仅 gzip | gzip + Draco |
| --- | --- | --- | --- |
| 首次加载 | 14.6 s | 10.7 s | **6.4 s** |
| 再次打开 | 14.6 s | 2.0 s | **约 2 s**（304，0 字节） |

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
