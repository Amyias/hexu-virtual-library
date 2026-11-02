# 句向量模型

`model_int8.onnx` 与 `vocab.txt` 来自 [Xenova/bge-small-zh-v1.5](https://huggingface.co/Xenova/bge-small-zh-v1.5)（固定在提交 `75c43b069aac4d136ba6bc1122f995fedcfd2781`），是 BAAI 的 [bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5) 的 ONNX 转换与 int8 量化版本，按 MIT 许可分发。

和序图书馆用它给书中段落生成句向量，与全文索引融合检索（`tools/embedder.py`、`tools/book_text_search.py`）。
