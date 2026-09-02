"""도입 검토용 벤치마크.

의사결정에 필요한 네 가지를 잰다.

  1. voices       화자별 전사 정확도 + 파이프라인(VAD 분절) 재현성
  2. latency      호출 지연 분포 p50/p95/p99 — 실시간 가능 여부
  3. concurrency  동시 요청을 올리며 포화점 탐색 — 동시 사용자 수용량
  4. longform     장문 오디오 처리 — 실제 통화 길이에서의 거동
  5. cost         오디오 1분당 토큰 — 원가 산정 입력값

    python benchmark.py [voices|latency|concurrency|longform|cost]

결과는 benchmark_results.json 에 남는다.
"""

import asyncio
import json
import pathlib
import statistics
import sys
import time
import wave

from server.audio import duration_s, resample_int16, to_mono_int16
from server.config import SAMPLE_RATE, Settings
from server.stt import SttClient

HERE = pathlib.Path(__file__).resolve().parent
SAMPLES = sorted((HERE.parent).glob("sample-*.wav")) or sorted((HERE / "samples").glob("*.wav"))

results: dict = {}


def load(path) -> bytes:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
        mono = to_mono_int16(raw, w.getnchannels(), w.getsampwidth())
        return resample_int16(mono, w.getframerate(), SAMPLE_RATE)


def clip(pcm: bytes, seconds: float) -> bytes:
    return pcm[: int(seconds * SAMPLE_RATE) * 2]


def norm(s: str) -> str:
    return "".join(c for c in (s or "") if not c.isspace() and c not in ".,!?-·")


def cer(ref: str, hyp: str) -> float:
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


def pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * p))]


# ------------------------------------------------------------------ 1. 화자별

async def bench_voices(stt: SttClient) -> None:
    print("\n[1] 화자별 전사 — 같은 오디오를 3회 반복해 재현성도 본다")
    out = {}
    for path in SAMPLES:
        pcm = load(path)
        runs = []
        for _ in range(3):
            t = await stt.transcribe(pcm)
            if t.ok:
                runs.append(t)
        if not runs:
            print(f"  {path.name:<28} 전부 실패")
            continue
        ref = runs[0].text
        spread = [cer(ref, r.text) for r in runs[1:]]
        tps = runs[0].total_tokens / runs[0].audio_s
        print(f"  {path.name:<28} {runs[0].audio_s:5.2f}s  "
              f"{runs[0].total_tokens:>5}tok  {tps:5.1f}tok/s  "
              f"반복간 CER {max(spread) if spread else 0:.1%}")
        print(f"      {runs[0].text}")
        out[path.name] = {
            "audio_s": runs[0].audio_s,
            "tokens": runs[0].total_tokens,
            "tokens_per_s": tps,
            "text": ref,
            "repeat_cer_max": max(spread) if spread else 0.0,
            "latencies": [r.latency_s for r in runs],
        }
    results["voices"] = out


# ------------------------------------------------------------------ 2. 지연

async def bench_latency(stt: SttClient) -> None:
    print("\n[2] 지연 분포 — 실시간 대화에서 쓰는 길이대로")
    pcm = load(SAMPLES[0])
    out = {}
    for dur in (1.0, 2.0, 4.0, 8.0):
        lats, fails = [], 0
        for _ in range(15):
            t = await stt.transcribe(clip(pcm, dur))
            if t.ok:
                lats.append(t.latency_s)
            else:
                fails += 1
        if not lats:
            continue
        rtf = statistics.median(lats) / dur
        print(f"  {dur:4.1f}s  n=15  p50 {1000*statistics.median(lats):4.0f}ms  "
              f"p95 {1000*pct(lats,0.95):4.0f}ms  p99 {1000*pct(lats,0.99):4.0f}ms  "
              f"RTF {rtf:.3f}  실패 {fails}")
        out[dur] = {
            "n": len(lats), "fails": fails,
            "p50_ms": 1000 * statistics.median(lats),
            "p95_ms": 1000 * pct(lats, 0.95),
            "p99_ms": 1000 * pct(lats, 0.99),
            "rtf": rtf,
        }
    results["latency"] = out


# ------------------------------------------------------------------ 3. 동시성

async def bench_concurrency(stt: SttClient) -> None:
    print("\n[3] 동시 요청 — 포화점과 수용량")
    pcm = clip(load(SAMPLES[0]), 4.0)
    out = {}
    for n in (1, 4, 8, 16, 32):
        t0 = time.perf_counter()
        res = await asyncio.gather(*(stt.transcribe(pcm) for _ in range(n)))
        wall = time.perf_counter() - t0
        ok = [r for r in res if r.ok]
        lats = [r.latency_s for r in ok]
        errs = [r.error for r in res if not r.ok]
        rps = n / wall
        audio_x = (n * 4.0) / wall  # 실시간 대비 몇 배 오디오를 처리했나
        print(f"  n={n:>3}  wall {wall:5.2f}s  성공 {len(ok):>3}/{n}  "
              f"p50 {1000*statistics.median(lats) if lats else 0:5.0f}ms  "
              f"p95 {1000*pct(lats,0.95):5.0f}ms  {rps:5.1f} req/s  "
              f"오디오 {audio_x:5.1f}x 실시간")
        if errs:
            print(f"      오류 예시: {errs[0][:120]}")
        out[n] = {
            "wall_s": wall, "ok": len(ok), "total": n,
            "p50_ms": 1000 * statistics.median(lats) if lats else 0,
            "p95_ms": 1000 * pct(lats, 0.95),
            "req_per_s": rps,
            "audio_realtime_x": audio_x,
            "errors": errs[:3],
        }
        await asyncio.sleep(1.0)
    results["concurrency"] = out


# ------------------------------------------------------------------ 4. 장문

async def bench_longform(stt: SttClient) -> None:
    print("\n[4] 장문 — 샘플을 이어붙여 길이를 늘린다")
    joined = b"".join(load(p) for p in SAMPLES)
    out = {}
    for dur in (8.0, 16.0, 32.0, duration_s(joined)):
        pcm = clip(joined, dur)
        t = await stt.transcribe(pcm)
        if not t.ok:
            print(f"  {dur:5.1f}s  실패: {t.error[:100]}")
            continue
        tps = t.total_tokens / t.audio_s
        print(f"  {t.audio_s:5.1f}s  {t.latency_s*1000:5.0f}ms  {t.total_tokens:>6}tok  "
              f"{tps:5.1f}tok/s  RTF {t.latency_s/t.audio_s:.3f}  글자 {len(norm(t.text))}")
        out[round(t.audio_s, 1)] = {
            "latency_ms": t.latency_s * 1000,
            "tokens": t.total_tokens,
            "tokens_per_s": tps,
            "rtf": t.latency_s / t.audio_s,
            "chars": len(norm(t.text)),
            "prompt_tokens": t.prompt_tokens,
            "completion_tokens": t.completion_tokens,
        }
    results["longform"] = out


# ------------------------------------------------------------------ 5. 원가

async def bench_cost(stt: SttClient) -> None:
    print("\n[5] 원가 산정 입력값 — 오디오 1분당 토큰")
    pcm = load(SAMPLES[0])
    rows = []
    for dur in (1.0, 2.0, 5.0, 8.0):
        t = await stt.transcribe(clip(pcm, dur))
        if t.ok:
            rows.append((t.audio_s, t.prompt_tokens, t.completion_tokens, t.total_tokens))
            print(f"  {t.audio_s:5.2f}s  prompt {t.prompt_tokens:>5}  "
                  f"completion {t.completion_tokens:>4}  total {t.total_tokens:>5}")
    if rows:
        # 선형 회귀 없이 최장 구간 기준으로 초당 계수를 잡는다.
        a, p, c, tot = rows[-1]
        print(f"\n  초당: prompt {p/a:.1f}  completion {c/a:.1f}  total {tot/a:.1f} tok/s")
        print(f"  1분당: prompt {60*p/a:,.0f}  completion {60*c/a:,.0f}  total {60*tot/a:,.0f} tok")
        results["cost"] = {
            "rows": rows,
            "prompt_per_s": p / a,
            "completion_per_s": c / a,
            "total_per_s": tot / a,
        }


# ------------------------------------------------------------------ main

async def main() -> None:
    which = sys.argv[1:] or ["voices", "latency", "concurrency", "longform", "cost"]
    s = Settings.from_env()
    # 서버 기본값(8)을 그대로 쓰면 클라이언트 세마포어가 먼저 걸려
    # API 쪽 포화점이 아니라 우리 코드의 상한을 재게 된다.
    s.max_concurrent_requests = 64
    # 재시도가 켜져 있으면 실패가 지연으로 흡수돼 포화점이 흐려진다.
    s.max_retries = 0
    stt = SttClient(s)
    print(f"모델 {s.model}   샘플 {len(SAMPLES)}개   "
          f"동시상한 {s.max_concurrent_requests}   재시도 {s.max_retries}회(측정용 off)")

    if "voices" in which:
        await bench_voices(stt)
    if "latency" in which:
        await bench_latency(stt)
    if "concurrency" in which:
        await bench_concurrency(stt)
    if "longform" in which:
        await bench_longform(stt)
    if "cost" in which:
        await bench_cost(stt)

    await stt.aclose()
    (HERE / "benchmark_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str)
    )
    print("\n저장: benchmark_results.json")


if __name__ == "__main__":
    asyncio.run(main())
