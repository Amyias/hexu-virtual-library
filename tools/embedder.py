"""Sentence vectors for 小和's book search: bge-small-zh-v1.5 (BAAI, MIT), int8 ONNX, 512 numbers
per passage, on the onnxruntime the reply voice already uses. Words in different clothes meet
here: 「主角的妈妈」 and 「他的母亲」 share no characters for the full-text index, but their
vectors lie close. tools/book_text_search.py fuses both rankings.

The tokenizer is BERT's own, written out rather than pulled in as a library: every CJK character
is a token, punctuation splits, the rest goes through WordPiece against vocab.txt. Case is kept
(the model was trained without lower-casing). tests/test_embedder.py checks it against the
model's published tokenizer.json.

Model files live in a folder of their own (models/embed beside the site when packaged,
.cache/models/embed in a checkout, or HEXU_EMBED_MODEL_DIR). Without them search uses the
full-text index alone, as before.
"""
import os
import threading
import unicodedata
from pathlib import Path

MODEL_FILE = "model_int8.onnx"
VOCAB_FILE = "vocab.txt"
MAX_TOKENS = 256  # passages are about 300 characters; the model accepts 512
BATCH = 16
# BGE suggests prefixing short queries with 「为这个句子生成表示以用于检索相关文章：」; v1.5 says it
# is optional, and measured on questions about novel passages it hurt (2 of 5 found with it, 4–5
# without, in fp32, fp16 and both int8 builds alike). Queries are encoded as plain text.


def model_dir(site_root=None, frozen=False):
    override = os.environ.get("HEXU_EMBED_MODEL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if frozen and site_root:
        return Path(site_root) / "models" / "embed"
    return Path(__file__).resolve().parents[1] / ".cache" / "models" / "embed"


def is_cjk(char):
    code = ord(char)
    return (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x20000 <= code <= 0x2A6DF
            or 0x2A700 <= code <= 0x2CEAF or 0xF900 <= code <= 0xFAFF or 0x2F800 <= code <= 0x2FA1F)


def is_punctuation(char):
    code = ord(char)
    if 33 <= code <= 47 or 58 <= code <= 64 or 91 <= code <= 96 or 123 <= code <= 126:
        return True
    return unicodedata.category(char).startswith("P")


class Tokenizer:
    def __init__(self, vocab_path):
        lines = Path(vocab_path).read_text(encoding="utf-8").splitlines()
        self.vocab = {token: index for index, token in enumerate(lines)}
        self.unk = self.vocab["[UNK]"]
        self.cls = self.vocab["[CLS]"]
        self.sep = self.vocab["[SEP]"]

    def words(self, text):
        """BERT's basic tokenisation: control characters dropped, whitespace normalised, each
        CJK character and each punctuation mark a word of its own."""
        out, current = [], []
        for char in text:
            code = ord(char)
            if code == 0 or code == 0xFFFD or (unicodedata.category(char) in ("Cc", "Cf") and char not in "\t\n\r"):
                continue
            if char.isspace():
                if current:
                    out.append("".join(current))
                    current = []
            elif is_cjk(char) or is_punctuation(char):
                if current:
                    out.append("".join(current))
                    current = []
                out.append(char)
            else:
                current.append(char)
        if current:
            out.append("".join(current))
        return out

    def wordpiece(self, word):
        if len(word) > 100:
            return [self.unk]
        pieces, start = [], 0
        while start < len(word):
            end = len(word)
            while end > start:
                piece = word[start:end] if start == 0 else "##" + word[start:end]
                if piece in self.vocab:
                    pieces.append(self.vocab[piece])
                    break
                end -= 1
            else:
                return [self.unk]
            start = end
        return pieces

    def encode(self, text, limit=MAX_TOKENS):
        ids = [piece for word in self.words(text) for piece in self.wordpiece(word)]
        return [self.cls, *ids[: limit - 2], self.sep]


class Embedder:
    """Loaded on first use and shared; encode() is serialised, the session is not reentrant."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.session = None
        self.tokenizer = None
        self.failure = None
        self.lock = threading.Lock()

    def state(self):
        missing = [name for name in (MODEL_FILE, VOCAB_FILE) if not (self.directory / name).is_file()]
        if missing:
            return False, "缺少向量模型：" + "、".join(missing)
        if self.failure is None:
            try:
                import numpy  # noqa: F401
                import onnxruntime  # noqa: F401
                self.failure = ""
            except ImportError as error:
                self.failure = f"缺少依赖：{error.name}"
        return (not self.failure), self.failure

    def _load(self):
        if self.session is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            self.session = ort.InferenceSession(str(self.directory / MODEL_FILE), options,
                                                providers=["CPUExecutionProvider"])
            self.tokenizer = Tokenizer(self.directory / VOCAB_FILE)
            self.inputs = {item.name for item in self.session.get_inputs()}

    def encode(self, texts):
        """Unit-length float32 vectors, one row per text."""
        import numpy as np

        with self.lock:
            self._load()
            rows = []
            for start in range(0, len(texts), BATCH):
                batch = [self.tokenizer.encode(text) for text in texts[start:start + BATCH]]
                width = max(len(ids) for ids in batch)
                ids = np.zeros((len(batch), width), np.int64)
                mask = np.zeros((len(batch), width), np.int64)
                for row, tokens in enumerate(batch):
                    ids[row, :len(tokens)] = tokens
                    mask[row, :len(tokens)] = 1
                feed = {"input_ids": ids, "attention_mask": mask}
                if "token_type_ids" in self.inputs:
                    feed["token_type_ids"] = np.zeros_like(ids)
                hidden = self.session.run(None, feed)[0]
                cls = hidden[:, 0, :]  # BGE pools by the [CLS] token
                rows.append(cls / np.linalg.norm(cls, axis=1, keepdims=True).clip(min=1e-12))
            return np.concatenate(rows).astype(np.float32) if rows else np.zeros((0, 512), np.float32)
