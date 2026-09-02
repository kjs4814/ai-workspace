"""WebSocket 경로까지 포함한 종단 검증.

simulate.py 는 Session 을 직접 호출하므로 app.py 의 WS 처리·프로토콜은 검증되지 않는다.
이 스크립트는 브라우저가 하는 일(20ms raw PCM 프레임을 실시간 속도로 전송)을 그대로 흉내낸다.

    python ws_test.py [ws://host:port/ws] [wav경로] [--pad N]
"""

import asyncio
import json
import pathlib
import sys
import time
import wave

import httpx

from server.audio import resample_int16, to_mono_int16
from server.config import FRAME_BYTES, FRAME_MS, SAMPLE_RATE

# 스크립트 위치 기준으로 잡는다. 어디서 실행하든, 폴더를 통째로 옮겨도 동작한다.
SAMPLE_WAV = str(pathlib.Path(__file__).resolve().parent / "samples" / "sample-female-calm.wav")


def load(path: str, pad_s: float) -> bytes:
    with wave.open(path, "rb") as w:
        raw = w.readframes(w.getnframes())
        pcm = resample_int16(
            to_mono_int16(raw, w.getnchannels(), w.getsampwidth()),
            w.getframerate(),
            SAMPLE_RATE,
        )
    if pad_s:
        sil = bytes(int(pad_s * SAMPLE_RATE) * 2)
        pcm = sil + pcm + sil
    return pcm


async def main() -> None:
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = argv[0] if argv else "ws://127.0.0.1:8848/ws"
    path = argv[1] if len(argv) > 1 else SAMPLE_WAV
    pad = 0.0
    if "--pad" in sys.argv:
        pad = float(sys.argv[sys.argv.index("--pad") + 1])

    pcm = load(path, pad)
    print(f"→ {url}\n   {path}  {len(pcm) / 2 / SAMPLE_RATE:.2f}s\n")

    t0 = time.monotonic()
    done = asyncio.Event()

    async with httpx.AsyncClient() as client:
        cfg = (await client.get(url.replace("ws://", "http://").replace("/ws", "/api/config"))).json()
        print(f"   /api/config → {cfg}\n")

    import websockets  # noqa: PLC0415

    async with websockets.connect(url, max_size=None) as ws:

        async def reader() -> None:
            async for raw in ws:
                ev = json.loads(raw)
                el = time.monotonic() - t0
                k = ev["type"]
                if k == "vad":
                    print(f"{el:6.2f}s [vad:{ev['state']}] utt={ev['utt']}")
                elif k == "interim":
                    print(f"{el:6.2f}s [잠정] ({ev['audio_s']}s {ev['latency_ms']}ms "
                          f"{ev['tokens']}tok) {ev['text']}")
                elif k == "final":
                    print(f"{el:6.2f}s [확정] ({ev['reason']} {ev['audio_s']}s "
                          f"{ev['latency_ms']}ms {ev['tokens']}tok) {ev['text']}")
                elif k == "dropped":
                    print(f"{el:6.2f}s [차단] {ev['reason']} ({ev.get('audio_s')}s "
                          f"flatness={ev.get('flatness')} band_ratio={ev.get('band_ratio')})")
                elif k == "warn":
                    print(f"{el:6.2f}s [경고] {ev['where']}: {ev['message'][:120]}")
                elif k == "error":
                    print(f"{el:6.2f}s [오류] {ev['where']}: {ev['message']}")
                elif k == "done":
                    print(f"\n최종 전사\n  {ev['transcript']}\n\n통계")
                    for kk, vv in ev["stats"].items():
                        print(f"  {kk:<20} {vv}")
                    done.set()

        task = asyncio.create_task(reader())

        frame_s = FRAME_MS / 1000
        next_t = time.monotonic()
        for i in range(len(pcm) // FRAME_BYTES):
            await ws.send(pcm[i * FRAME_BYTES : (i + 1) * FRAME_BYTES])
            next_t += frame_s
            d = next_t - time.monotonic()
            if d > 0:
                await asyncio.sleep(d)

        await ws.send(json.dumps({"type": "stop"}))
        await asyncio.wait_for(done.wait(), timeout=30)
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
