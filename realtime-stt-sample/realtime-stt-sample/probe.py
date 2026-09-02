"""RAG Suite whisper-large-v3 실측 probe.

미확인 항목을 직접 호출해서 확인한다:
  1. baseline    전체 파일 1회 전사 (정확도 / 지연 / usage 기준값)
  2. params      language / prompt / temperature / verbose_json 지원 여부
  3. latency     chunk 길이별 왕복 시간 (실시간 chunk 크기 결정용)
  4. billing     전체 1회 vs 짧은 chunk N회 토큰 비교 (30초 패딩 과금 여부)
  5. silence     무음 chunk hallucination 발생 여부
  6. concurrency 동시 요청 허용 범위 (rate limit 탐색)

토큰은 환경변수 RAG_SUITE_TOKEN 에서만 읽는다. 파일에 하드코딩하지 않는다.
"""

import io
import json
import os
import statistics
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import requests

BASE_URL = os.environ["RAG_SUITE_BASE_URL"].rstrip("/")
TOKEN = os.environ["RAG_SUITE_TOKEN"]
AUDIO_PATH = os.environ.get("PROBE_AUDIO", "../sample-female-calm.wav")
MODEL = "openai/whisper-large-v3"

URL = f"{BASE_URL}/v1/audio/transcriptions"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

results = {}


# ---------------------------------------------------------------- WAV helpers

def load_pcm(path):
    with wave.open(path, "rb") as w:
        assert w.getcomptype() == "NONE", "비압축 PCM WAV만 지원"
        return {
            "channels": w.getnchannels(),
            "sampwidth": w.getsampwidth(),
            "rate": w.getframerate(),
            "frames": w.readframes(w.getnframes()),
            "nframes": w.getnframes(),
        }


def slice_wav(pcm, start_sec, dur_sec):
    """PCM 구간을 잘라 헤더가 붙은 독립 WAV 바이트로 반환."""
    fps = pcm["rate"]
    bpf = pcm["channels"] * pcm["sampwidth"]
    start = int(start_sec * fps)
    end = min(int((start_sec + dur_sec) * fps), pcm["nframes"])
    if end <= start:
        return None
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(pcm["channels"])
        w.setsampwidth(pcm["sampwidth"])
        w.setframerate(fps)
        w.writeframes(pcm["frames"][start * bpf:end * bpf])
    return buf.getvalue()


def silent_wav(pcm, dur_sec):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(pcm["channels"])
        w.setsampwidth(pcm["sampwidth"])
        w.setframerate(pcm["rate"])
        w.writeframes(b"\x00" * int(dur_sec * pcm["rate"]) * pcm["channels"] * pcm["sampwidth"])
    return buf.getvalue()


# ---------------------------------------------------------------- API call

def transcribe(audio_bytes, name="chunk.wav", **form):
    data = {"model": MODEL, "response_format": "json", **form}
    t0 = time.perf_counter()
    try:
        r = requests.post(
            URL,
            headers=HEADERS,
            files={"file": (name, audio_bytes, "audio/wav")},
            data=data,
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc), "elapsed": time.perf_counter() - t0}
    elapsed = time.perf_counter() - t0
    out = {"ok": r.ok, "status": r.status_code, "elapsed": elapsed}
    try:
        out["body"] = r.json()
    except ValueError:
        out["body"] = r.text[:500]
    out["ratelimit_headers"] = {
        k: v for k, v in r.headers.items() if "ratelimit" in k.lower() or "retry" in k.lower()
    }
    return out


def usage_of(res):
    body = res.get("body")
    return body.get("usage") if isinstance(body, dict) else None


def text_of(res):
    body = res.get("body")
    return body.get("text") if isinstance(body, dict) else None


def show(label, res):
    u = usage_of(res) or {}
    print(
        f"  {label:<34} {res.get('status', '---')} "
        f"{res['elapsed']:6.2f}s  tok={u.get('total_tokens', '-'):>6} "
        f"sec={u.get('seconds', '-')}"
    )
    if not res.get("ok"):
        print(f"      ERR {str(res.get('body') or res.get('error'))[:220]}")


# ---------------------------------------------------------------- probes

def probe_baseline(pcm, dur):
    print("\n[1] baseline — 전체 파일 1회")
    res = transcribe(slice_wav(pcm, 0, dur), "full.wav")
    show("full file", res)
    print(f"      text: {text_of(res)!r}")
    if res.get("ratelimit_headers"):
        print(f"      ratelimit headers: {res['ratelimit_headers']}")
    results["baseline"] = res
    return res


def probe_params(pcm, dur):
    print("\n[2] 파라미터 지원 여부")
    audio = slice_wav(pcm, 0, dur)
    cases = {
        "language=ko": {"language": "ko"},
        "temperature=0": {"temperature": "0"},
        "prompt=<context>": {"prompt": "kt cloud RAG Suite 음성 데모입니다."},
        "response_format=verbose_json": {"response_format": "verbose_json"},
        "response_format=text": {"response_format": "text"},
        "response_format=srt": {"response_format": "srt"},
        "timestamp_granularities[]=word": {
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        },
    }
    out = {}
    for label, form in cases.items():
        res = transcribe(audio, "full.wav", **form)
        show(label, res)
        body = res.get("body")
        if label.startswith("response_format=verbose") and res.get("ok") and isinstance(body, dict):
            print(f"      keys: {sorted(body.keys())}")
            if "segments" in body and body["segments"]:
                print(f"      segment[0]: {json.dumps(body['segments'][0], ensure_ascii=False)[:200]}")
            if "words" in body and body["words"]:
                print(f"      word[0..2]: {json.dumps(body['words'][:3], ensure_ascii=False)[:200]}")
        out[label] = res
    results["params"] = out


def probe_latency(pcm, dur):
    print("\n[3] chunk 길이별 지연 (각 2회)")
    out = {}
    for clen in (1, 2, 3, 5, int(dur)):
        audio = slice_wav(pcm, 0, clen)
        if audio is None:
            continue
        runs = [transcribe(audio, f"c{clen}.wav", language="ko") for _ in range(2)]
        times = [r["elapsed"] for r in runs if r.get("ok")]
        toks = [(usage_of(r) or {}).get("total_tokens") for r in runs if r.get("ok")]
        med = statistics.median(times) if times else float("nan")
        print(f"  {clen:>2}s chunk  median {med:6.2f}s   tokens={toks}")
        out[clen] = {"times": times, "tokens": toks}
    results["latency"] = out


def probe_billing(pcm, dur):
    print("\n[4] 과금 방식 — 전체 1회 vs 1초 chunk N회")
    whole = transcribe(slice_wav(pcm, 0, dur), "whole.wav", language="ko")
    show(f"whole {dur:.1f}s x1", whole)
    whole_tok = (usage_of(whole) or {}).get("total_tokens", 0)

    n = int(dur)
    chunk_res = []
    for i in range(n):
        r = transcribe(slice_wav(pcm, i, 1), f"s{i}.wav", language="ko")
        chunk_res.append(r)
    chunk_tok = sum((usage_of(r) or {}).get("total_tokens", 0) for r in chunk_res)
    chunk_sec = sum((usage_of(r) or {}).get("seconds", 0) for r in chunk_res)
    print(f"  1s chunk x{n}                       total_tokens={chunk_tok} seconds={chunk_sec}")
    if whole_tok:
        print(f"\n  >>> 배율: {chunk_tok / whole_tok:.2f}x  (1.0 근처면 duration 기반, 3x 이상이면 chunk 페널티 큼)")
    print(f"  이어붙인 텍스트: {''.join(text_of(r) or '' for r in chunk_res)!r}")
    results["billing"] = {"whole_tokens": whole_tok, "chunk_tokens": chunk_tok, "n": n}


def probe_silence(pcm):
    print("\n[5] 무음 chunk hallucination")
    out = {}
    for clen in (1, 3):
        res = transcribe(silent_wav(pcm, clen), f"sil{clen}.wav", language="ko")
        show(f"silence {clen}s", res)
        print(f"      text: {text_of(res)!r}")
        out[clen] = text_of(res)
    results["silence"] = out


def probe_concurrency(pcm):
    print("\n[6] 동시 요청 (2 → 4 → 8)")
    audio = slice_wav(pcm, 0, 2)
    out = {}
    for n in (2, 4, 8):
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n) as ex:
            runs = list(ex.map(lambda _: transcribe(audio, "cc.wav", language="ko"), range(n)))
        wall = time.perf_counter() - t0
        codes = [r.get("status") for r in runs]
        ok = sum(1 for r in runs if r.get("ok"))
        print(f"  n={n:>2}  wall {wall:6.2f}s  ok={ok}/{n}  status={codes}")
        for r in runs:
            if r.get("ratelimit_headers"):
                print(f"      ratelimit: {r['ratelimit_headers']}")
                break
        if ok < n:
            print(f"      실패 본문: {str(runs[codes.index(next(c for c in codes if c != 200))].get('body'))[:200]}")
        out[n] = {"wall": wall, "ok": ok, "codes": codes}
        time.sleep(1)
    results["concurrency"] = out


def probe_cors():
    print("\n[7] CORS preflight (브라우저 직접 호출 가능 여부)")
    try:
        r = requests.options(
            URL,
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
            timeout=20,
        )
        cors = {k: v for k, v in r.headers.items() if k.lower().startswith("access-control")}
        print(f"  status={r.status_code}  cors_headers={cors or 'NONE'}")
        results["cors"] = {"status": r.status_code, "headers": cors}
    except Exception as exc:  # noqa: BLE001
        print(f"  실패: {exc!r}")
        results["cors"] = {"error": repr(exc)}


# ---------------------------------------------------------------- main

def main():
    pcm = load_pcm(AUDIO_PATH)
    dur = pcm["nframes"] / pcm["rate"]
    print(f"audio: {AUDIO_PATH}")
    print(f"  {pcm['rate']}Hz {pcm['channels']}ch {pcm['sampwidth'] * 8}bit  {dur:.2f}s")
    print(f"endpoint: {URL}")

    only = sys.argv[1:] or ["baseline", "params", "latency", "billing", "silence", "concurrency", "cors"]
    if "baseline" in only:
        probe_baseline(pcm, dur)
    if "params" in only:
        probe_params(pcm, dur)
    if "latency" in only:
        probe_latency(pcm, dur)
    if "billing" in only:
        probe_billing(pcm, dur)
    if "silence" in only:
        probe_silence(pcm)
    if "concurrency" in only:
        probe_concurrency(pcm)
    if "cors" in only:
        probe_cors()

    with open("probe_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print("\n저장: probe_results.json")


if __name__ == "__main__":
    main()
