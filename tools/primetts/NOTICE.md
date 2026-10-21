# PrimeTTS（第三方）

- 来源：<https://huggingface.co/Luigi/PrimeTTS>
- 许可证：Apache License 2.0（<https://www.apache.org/licenses/LICENSE-2.0>）
- 本目录的 `text_norm.py` 原样取自该仓库 `scripts/text_norm.py`，只在文件头加了来源说明。
- `tools/tts.py` 的注音前端改写自该仓库 `scripts/frontend_bopomofo.py`：符号表与音素规则相同，
  注音由 g2pW 改为 pypinyin（避免额外下载数百 MB 的 g2pW 与 BERT 模型），英文只念字母与数字。
- 模型 `v21_mbistft_16k/primetts_v21_3voice.onnx`（SHA-256
  `0cf64ad010a9b92201222533900ece31562a0181e7a8e435e5de83b3d72b4bdf`）不进入本仓库，
  由 `tools/package-local.mjs` 从上述地址下载并校验。
- 模型作者说明：v2.1 的三个声音由 AI 合成数据训练（教师模型为 Microsoft VibeVoice，MIT），
  产品中应标明为合成语音。本项目使用其中的女声「欣然」（sid 0）。
