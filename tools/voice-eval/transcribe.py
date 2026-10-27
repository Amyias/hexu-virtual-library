"""The voice evaluation's Python half (driven by tools/voice-eval.mjs).

    transcribe LIST OUT   LIST: [{"key", "path"}] of 16 kHz mono WAV segments. Each is decoded by
                          the program's own transcribe() in tools/asr-server.py, the same model,
                          settings and silence check. OUT: {key: {"text", "seconds"}}.
    synth PROMPTS DIR     Speak every prompt with the local PrimeTTS voice into DIR/<id>.wav: a
                          stand-in recording to prove the pipeline end to end. One synthetic voice
                          says nothing about how well real readers are heard.

Paths only arrive as arguments and files; nothing is read from or sent to the network.
"""
import importlib.util
import io
import json
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

LEAD, GAP, TAIL = 0.8, 1.2, 1.0  # seconds of quiet around and between the parts of a prompt
NOISE_RMS = 0.004  # a steady hiss under the noise prompts, well below the segmenter's threshold
QUIET = 0.35  # level of the prompts asked to be said softly or from across the room


def server():
    spec = importlib.util.spec_from_file_location("voice_eval_server", ROOT / "tools" / "asr-server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def transcribe(listing, out):
    asr = server()
    ready, state = asr.model_state()
    if not ready:
        sys.exit("识别模型不可用：" + str(state.get("reason")))
    results = {}
    for item in json.loads(Path(listing).read_text(encoding="utf-8")):
        status, payload = asr.transcribe(Path(item["path"]).read_bytes())
        results[item["key"]] = {"text": payload.get("text", "") if status == 200 else "",
                                "seconds": payload.get("seconds", 0.0), "status": status}
    Path(out).write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")


def samples_of(raw):
    import numpy as np

    with wave.open(io.BytesIO(raw), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768


def synth(prompts_file, directory):
    import numpy as np

    asr = server()
    speaker = asr.SPEAKER
    ready, state = speaker.state()
    if not ready:
        sys.exit("语音合成模型不可用：" + str(state.get("reason")))
    rate = 16000
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    for prompt in json.loads(Path(prompts_file).read_text(encoding="utf-8"))["prompts"]:
        pieces = [np.zeros(int(LEAD * rate), np.float32)]
        for index, part in enumerate(prompt["say"]):
            if index:
                pieces.append(np.zeros(int(GAP * rate), np.float32))
            pieces.append(samples_of(speaker.synthesize(part)))
        pieces.append(np.zeros(int(TAIL * rate), np.float32))
        audio = np.concatenate(pieces)
        hint = prompt.get("hint", "")
        if "三米" in hint or "轻" in hint:
            audio = audio * QUIET
        if prompt.get("noise"):
            audio = audio + rng.normal(0, NOISE_RMS, audio.shape).astype(np.float32)
        (target / f"{prompt['id']}.wav").write_bytes(speaker_wav(audio, rate))


def speaker_wav(audio, rate):
    import tts

    return tts.wav_bytes(audio, rate)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("transcribe", "synth"):
        sys.exit("用法：transcribe LIST OUT | synth PROMPTS DIR")
    (transcribe if sys.argv[1] == "transcribe" else synth)(sys.argv[2], sys.argv[3])
