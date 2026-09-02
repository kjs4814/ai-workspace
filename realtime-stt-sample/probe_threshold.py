"""hallucination 필터 임계값 실측.

verbose_json 의 no_speech_prob 는 null 로 오므로 avg_logprob / compression_ratio 로
무음·잡음 구간을 걸러내야 한다. 실제 발화와 무음/잡음의 값 분포를 비교한다.
"""

import io
import json
import math
import os
import random
import struct
import wave

import requests

BASE_URL = os.environ["RAG_SUITE_BASE_URL"].rstrip("/")
TOKEN = os.environ["RAG_SUITE_TOKEN"]
AUDIO_PATH = os.environ.get("PROBE_AUDIO", "../sample-female-calm.wav")
URL = f"{BASE_URL}/v1/audio/transcriptions"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
RATE = 16000


def wav_bytes(samples, rate=RATE):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def speech_slice(path, start, dur):
    with wave.open(path, "rb") as w:
        rate, bpf = w.getframerate(), w.getnchannels() * w.getsampwidth()
        w.setpos(int(start * rate))
        raw = w.readframes(int(dur * rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as o:
        o.setnchannels(1)
        o.setsampwidth(2)
        o.setframerate(rate)
        o.writeframes(raw[: len(raw) // bpf * bpf])
    return buf.getvalue()


def probe(label, audio):
    r = requests.post(
        URL,
        headers=HEADERS,
        files={"file": ("c.wav", audio, "audio/wav")},
        data={
            "model": "openai/whisper-large-v3",
            "response_format": "verbose_json",
            "language": "ko",
        },
        timeout=60,
    )
    if not r.ok:
        print(f"{label:<22} ERR {r.status_code} {r.text[:120]}")
        return None
    b = r.json()
    segs = b.get("segments") or []
    s = segs[0] if segs else {}
    print(
        f"{label:<22} logprob={s.get('avg_logprob'):>8}  "
        f"compr={s.get('compression_ratio')}  nospeech={s.get('no_speech_prob')}  "
        f"text={b.get('text')!r}"
    )
    return {
        "label": label,
        "avg_logprob": s.get("avg_logprob"),
        "compression_ratio": s.get("compression_ratio"),
        "no_speech_prob": s.get("no_speech_prob"),
        "text": b.get("text"),
        "nseg": len(segs),
    }


def main():
    out = []
    print("--- 무음 / 잡음 (걸러내야 하는 것) ---")
    for d in (1, 2, 3):
        out.append(probe(f"silence {d}s", wav_bytes([0] * int(RATE * d))))

    random.seed(0)
    for d, amp in ((2, 200), (2, 2000)):
        noise = [random.randint(-amp, amp) for _ in range(int(RATE * d))]
        out.append(probe(f"white-noise {d}s a{amp}", wav_bytes(noise)))

    # 60Hz 험 잡음
    hum = [int(500 * math.sin(2 * math.pi * 60 * t / RATE)) for t in range(RATE * 2)]
    out.append(probe("hum-60hz 2s", wav_bytes(hum)))

    print("\n--- 실제 발화 (통과시켜야 하는 것) ---")
    for start, d in ((0, 2), (0, 3), (2, 3), (0, 7.68)):
        out.append(probe(f"speech {start}s+{d}s", speech_slice(AUDIO_PATH, start, d)))

    good = [r for r in out if r and r["label"].startswith("speech")]
    bad = [r for r in out if r and not r["label"].startswith("speech")]
    gl = [r["avg_logprob"] for r in good if r["avg_logprob"] is not None]
    bl = [r["avg_logprob"] for r in bad if r["avg_logprob"] is not None]
    print("\n--- 분리 가능성 ---")
    print(f"발화   avg_logprob  min={min(gl):.3f}  max={max(gl):.3f}")
    if bl:
        print(f"무음/잡음 avg_logprob min={min(bl):.3f}  max={max(bl):.3f}")
        print(f"제안 임계값: avg_logprob > {(min(gl) + max(bl)) / 2:.2f} 통과")

    with open("threshold_results.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
