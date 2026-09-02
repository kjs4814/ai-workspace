"""마이크 없이 파이프라인을 검증한다.

WAV 파일을 20ms 프레임으로 잘라 실제 발화 속도대로 Session 에 흘려넣고,
서버가 브라우저로 보냈을 이벤트를 그대로 출력한다.

    python simulate.py [wav경로] [--fast] [--no-interim] [--pad N]

  --fast        실시간 대기 없이 최대 속도로 (지연 수치는 의미 없어짐)
  --no-interim  growing window 잠정 전사 끄기 (확정 경로만 비교용)
  --pad N       앞뒤에 N초 무음을 붙인다. VAD 게이팅/hallucination 필터 검증용.
"""

import asyncio
import pathlib
import sys
import time
import wave

from server.audio import resample_int16, to_mono_int16
from server.config import FRAME_BYTES, FRAME_MS, SAMPLE_RATE, Settings
from server.session import Session
from server.stt import SttClient

# 스크립트 위치 기준으로 잡는다. 어디서 실행하든, 폴더를 통째로 옮겨도 동작한다.
SAMPLE_WAV = str(pathlib.Path(__file__).resolve().parent / "samples" / "sample-female-calm.wav")

RESET, DIM, GREEN, YELLOW, RED, CYAN = (
    "\033[0m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[36m",
)


def load_16k_mono(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        raw = w.readframes(w.getnframes())
        mono = to_mono_int16(raw, w.getnchannels(), w.getsampwidth())
        return resample_int16(mono, w.getframerate(), SAMPLE_RATE)


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    path = args[0] if args else SAMPLE_WAV
    pad_s = 0.0
    for i, a in enumerate(sys.argv):
        if a == "--pad" and i + 1 < len(sys.argv):
            pad_s = float(sys.argv[i + 1])

    pcm = load_16k_mono(path)
    if pad_s:
        silence = bytes(int(pad_s * SAMPLE_RATE) * 2)
        pcm = silence + pcm + silence

    settings = Settings.from_env()
    if "--no-interim" in flags:
        settings.interim_enabled = False

    print(f"{CYAN}입력{RESET} {path}  {len(pcm) / 2 / SAMPLE_RATE:.2f}s @ {SAMPLE_RATE}Hz mono")
    print(f"{CYAN}설정{RESET} interim={settings.interim_enabled} "
          f"end_silence={settings.vad_end_silence_ms}ms "
          f"interim_interval={settings.interim_min_interval_s}s\n")

    t_start = time.monotonic()
    stt = SttClient(settings)

    async def emit(ev: dict) -> None:
        el = time.monotonic() - t_start
        kind = ev["type"]
        if kind == "vad":
            color = GREEN if ev["state"] == "speech" else DIM
            print(f"{el:6.2f}s {color}[vad:{ev['state']}]{RESET} utt={ev['utt']}")
        elif kind == "interim":
            print(f"{el:6.2f}s {YELLOW}[잠정]{RESET} ({ev['audio_s']}s "
                  f"{ev['latency_ms']}ms {ev['tokens']}tok) {DIM}{ev['text']}{RESET}")
        elif kind == "final":
            print(f"{el:6.2f}s {GREEN}[확정]{RESET} ({ev['reason']} {ev['audio_s']}s "
                  f"{ev['latency_ms']}ms {ev['tokens']}tok) {ev['text']}")
        elif kind == "dropped":
            print(f"{el:6.2f}s {RED}[차단]{RESET} {ev['reason']} "
                  f"({ev.get('audio_s')}s flatness={ev.get('flatness')} "
                  f"band_ratio={ev.get('band_ratio')})")
        elif kind == "warn":
            print(f"{el:6.2f}s {YELLOW}[경고]{RESET} {ev['where']}: {ev['message'][:120]}")
        elif kind == "error":
            print(f"{el:6.2f}s {RED}[오류]{RESET} {ev['where']}: {ev['message']}")

    session = Session(stt, settings, emit)

    realtime = "--fast" not in flags
    frame_s = FRAME_MS / 1000
    n_frames = len(pcm) // FRAME_BYTES
    next_t = time.monotonic()
    for i in range(n_frames):
        await session.feed(pcm[i * FRAME_BYTES : (i + 1) * FRAME_BYTES])
        if realtime:
            next_t += frame_s
            delay = next_t - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
        else:
            await asyncio.sleep(0)

    await session.flush()

    print(f"\n{CYAN}최종 전사{RESET}\n  {session.transcript}")
    st = session.stats.snapshot(settings)
    print(f"\n{CYAN}통계{RESET}")
    for k, v in st.items():
        print(f"  {k:<20} {v}")
    print(f"  {'wall_clock_s':<20} {time.monotonic() - t_start:.2f}")

    await session.close()
    await stt.aclose()


if __name__ == "__main__":
    asyncio.run(main())
