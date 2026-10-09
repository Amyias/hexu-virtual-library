# 语音识别模型

这个分支只放一样东西：**SenseVoice 语音识别模型**（sherpa-onnx 的 int8 量化版，中英日韩粤）。
源码在 `master`，模型在本分支，两边分开是因为 GitHub 与 Gitee 的限制不同：

| | 限制 | 影响 |
| --- | --- | --- |
| GitHub 单文件 | 100 MiB（硬限制） | 模型 228 MiB 装不下，所以切成 3 块 |
| Gitee 单文件 / 单仓库 | 50 MB / 500 MB | 76 MB 的块在 Gitee 那边根本推不上去，所以本分支只推 GitHub |

## 拼回去

**不用手动拼**。在 `master` 上运行打包命令即可，`tools/package-local.mjs` 会在本地没有模型时
自动从本分支取出分块、拼回、并核对下面的 SHA-256：

```
node tools/package-local.mjs
```

它做的事：读 `manifest.json` → 依次取出分块写进 `.cache/models/sense-voice/` → 按 `sha256`
校验整文件 → 校验通过才继续打包。校验不通过就直接报错，不会拿一个残缺的模型去打包。

手动拼也可以（Linux/macOS 下）：

```
cat model.int8.onnx.001 model.int8.onnx.002 model.int8.onnx.003 > model.int8.onnx
sha256sum model.int8.onnx   # 应等于 manifest.json 里的 sha256
```

## 内容

| 文件 | 大小 | 说明 |
| --- | --- | --- |
| `model.int8.onnx.001`…`003` | 各 76.1 MB | 模型分块，按序号顺序拼接 |
| `manifest.json` | 901 B | 分块大小、每块与整文件的 SHA-256、来源说明 |
| `tokens.txt` | 316 KB | 模型的词表，识别必需，未分块 |
| `LICENSE` | 71 B | 模型自带许可文件，随模型一起分发 |

## 来源与许可

模型是 **SenseVoice**（FunAudioLLM / Alibaba）的 sherpa-onnx 转换版，许可为 Apache-2.0 系列，
`LICENSE` 为模型自带的许可声明。原始发布地址：
<https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models>（
`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17`）。

识别完全在本机运行：模型读进内存后推理，音频不出这台机器。
