"""chunk 전략별 전사 정확도 측정.

실시간 스트리밍의 진짜 트레이드오프는 비용이 아니라 정확도다(과금은 duration 선형으로 확인됨).
어떤 분할 전략이 전체 파일 1회 전사에 얼마나 근접하는지 CER로 비교한다.

전략:
  fixed-Ns       N초 고정 분할, 겹침 없음
  growing        발화 시작부터 누적한 오디오를 매 tick 재전사 (부분 결과 표시용)
  overlap-Ns     N초 창 + 1초 겹침, 접미사 매칭 dedup
  prompt-chain   N초 고정 분할 + 직전 결과를 prompt로 전달
  vad            에너지 기반 무음 감지로 분절
"""

import io
import json
import os
import time
import wave

import requests

BASE_URL = os.environ["RAG_SUITE_BASE_URL"].rstrip("/")
TOKEN = os.environ["RAG_SUITE_TOKEN"]
AUDIO_PATH = os.environ.get("PROBE_AUDIO", "../sample-female-calm.wav")
MODEL = "openai/whisper-large-v3"
URL = f"{BASE_URL}/v1/audio/transcriptions"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def load_pcm(path):
    with wave.open(path, "rb") as w:
        return {
            "channels": w.getnchannels(),
            "sampwidth": w.getsampwidth(),
            "rate": w.getframerate(),
            "frames": w.readframes(w.getnframes()),
            "nframes": w.getnframes(),
        }


def slice_wav(pcm, start_sec, end_sec):
    fps, bpf = pcm["rate"], pcm["channels"] * pcm["sampwidth"]
    s, e = int(start_sec * fps), min(int(end_sec * fps), pcm["nframes"])
    if e <= s:
        return None
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(pcm["channels"])
        w.setsampwidth(pcm["sampwidth"])
        w.setframerate(fps)
        w.writeframes(pcm["frames"][s * bpf:e * bpf])
    return buf.getvalue()


def transcribe(audio, **form):
    r = requests.post(
        URL,
        headers=HEADERS,
        files={"file": ("c.wav", audio, "audio/wav")},
        data={"model": MODEL, "response_format": "json", "language": "ko", **form},
        timeout=120,
    )
    if not r.ok:
        return "", 0
    b = r.json()
    return b.get("text", ""), (b.get("usage") or {}).get("total_tokens", 0)


# ---------------------------------------------------------------- 평가

def norm(s):
    return "".join(ch for ch in (s or "") if not ch.isspace() and ch not in ".,!?-·")


def cer(ref, hyp):
    """문자 오류율 (Levenshtein / len(ref))."""
    r, h = norm(ref), norm(hyp)
    if not r:
        return 1.0
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i]
        for j, hc in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[len(h)] / len(r)


def dedup_join(prev_text, new_text, max_overlap=20):
    """prev 접미사와 new 접두사가 겹치면 잘라내고 이어붙인다."""
    a, b = prev_text.rstrip(), new_text.lstrip()
    for k in range(min(max_overlap, len(a), len(b)), 2, -1):
        if norm(a[-k:]) and norm(a[-k:]) == norm(b[:k]):
            return a + b[k:]
    return a + " " + b


def rms(pcm, start_sec, end_sec):
    import array
    fps, bpf = pcm["rate"], pcm["channels"] * pcm["sampwidth"]
    s, e = int(start_sec * fps), min(int(end_sec * fps), pcm["nframes"])
    a = array.array("h")
    a.frombytes(pcm["frames"][s * bpf:e * bpf])
    if not a:
        return 0.0
    return (sum(v * v for v in a) / len(a)) ** 0.5


# ---------------------------------------------------------------- 전략

def strat_fixed(pcm, dur, n):
    out, tok, lat = "", 0, []
    t = 0.0
    while t < dur:
        t0 = time.perf_counter()
        txt, tk = transcribe(slice_wav(pcm, t, t + n))
        lat.append(time.perf_counter() - t0)
        out += txt
        tok += tk
        t += n
    return out, tok, lat


def strat_prompt_chain(pcm, dur, n):
    out, tok, lat = "", 0, []
    t = 0.0
    while t < dur:
        t0 = time.perf_counter()
        txt, tk = transcribe(slice_wav(pcm, t, t + n), prompt=out[-200:])
        lat.append(time.perf_counter() - t0)
        out += txt
        tok += tk
        t += n
    return out, tok, lat


def strat_overlap(pcm, dur, n, ov=1.0):
    out, tok, lat = "", 0, []
    t = 0.0
    while t < dur:
        t0 = time.perf_counter()
        txt, tk = transcribe(slice_wav(pcm, max(0, t - ov), t + n))
        lat.append(time.perf_counter() - t0)
        out = dedup_join(out, txt) if out else txt
        tok += tk
        t += n
    return out, tok, lat


def strat_growing(pcm, dur, step):
    """매 step 초마다 처음부터 누적 재전사. 마지막 결과가 최종본."""
    out, tok, lat = "", 0, []
    t = step
    while t < dur + step:
        t0 = time.perf_counter()
        txt, tk = transcribe(slice_wav(pcm, 0, min(t, dur)))
        lat.append(time.perf_counter() - t0)
        out = txt
        tok += tk
        t += step
    return out, tok, lat


def strat_vad(pcm, dur, win=0.1, sil_thresh=None, min_sil=0.4, max_seg=8.0):
    """에너지 기반 무음 감지 분절. 무음 구간은 호출 자체를 건너뛴다."""
    levels = [(t, rms(pcm, t, t + win)) for t in [i * win for i in range(int(dur / win))]]
    peak = max(v for _, v in levels) or 1.0
    thr = sil_thresh if sil_thresh is not None else peak * 0.06

    segs, seg_start, sil_run = [], None, 0.0
    for t, v in levels:
        if v >= thr:
            if seg_start is None:
                seg_start = max(0.0, t - win)
            sil_run = 0.0
        else:
            if seg_start is not None:
                sil_run += win
                if sil_run >= min_sil or (t - seg_start) >= max_seg:
                    segs.append((seg_start, t))
                    seg_start, sil_run = None, 0.0
    if seg_start is not None:
        segs.append((seg_start, dur))

    out, tok, lat = "", 0, []
    for s, e in segs:
        t0 = time.perf_counter()
        txt, tk = transcribe(slice_wav(pcm, s, e))
        lat.append(time.perf_counter() - t0)
        out += txt
        tok += tk
    return out, tok, lat, segs


# ---------------------------------------------------------------- main

def main():
    pcm = load_pcm(AUDIO_PATH)
    dur = pcm["nframes"] / pcm["rate"]
    print(f"audio {dur:.2f}s  {pcm['rate']}Hz\n")

    ref, ref_tok = transcribe(slice_wav(pcm, 0, dur))
    print(f"REFERENCE (full 1-shot, {ref_tok} tok)\n  {ref!r}\n")

    rows = []

    def run(label, fn):
        res = fn()
        txt, tok, lat = res[0], res[1], res[2]
        e = cer(ref, txt)
        worst = max(lat) if lat else 0
        rows.append((label, e, tok, len(lat), worst))
        print(f"[{label}]  CER {e:5.1%}  tok {tok:>5}  calls {len(lat):>2}  max_lat {worst:.2f}s")
        print(f"  {txt!r}")
        if len(res) > 3:
            print(f"  segments: {[(round(s, 2), round(e2, 2)) for s, e2 in res[3]]}")
        print()
        return res

    for n in (1, 2, 3, 5):
        run(f"fixed-{n}s", lambda n=n: strat_fixed(pcm, dur, n))
    for n in (2, 3):
        run(f"overlap-{n}s+1s", lambda n=n: strat_overlap(pcm, dur, n))
    for n in (2, 3):
        run(f"prompt-chain-{n}s", lambda n=n: strat_prompt_chain(pcm, dur, n))
    run("growing-2s", lambda: strat_growing(pcm, dur, 2))
    run("vad", lambda: strat_vad(pcm, dur))

    print("=" * 72)
    print(f"{'전략':<20} {'CER':>8} {'tokens':>8} {'calls':>6} {'max_lat':>9}")
    print("-" * 72)
    for label, e, tok, calls, worst in sorted(rows, key=lambda r: r[1]):
        print(f"{label:<20} {e:>7.1%} {tok:>8} {calls:>6} {worst:>8.2f}s")
    print(f"{'(reference)':<20} {0:>7.1%} {ref_tok:>8} {1:>6} {'-':>9}")

    with open("quality_results.json", "w") as f:
        json.dump({"reference": ref, "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
