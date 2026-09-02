"""API 호출 없이 도는 검증. 토큰도 요금도 쓰지 않는다.

    python test_offline.py
"""

import math
import struct
import pathlib
import sys
import wave

import numpy as np

from server.audio import duration_s, pcm_to_wav, resample_int16, rms, tail, to_mono_int16
from server.config import SAMPLE_RATE, Settings
from server.spectral import is_speech_like, score
from server.vad import EnergyVad

# 스크립트 위치 기준으로 잡는다. 어디서 실행하든, 폴더를 통째로 옮겨도 동작한다.
SAMPLE_WAV = str(pathlib.Path(__file__).resolve().parent / "samples" / "sample-female-calm.wav")

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def sine(freq: float, dur: float, amp: int = 3000, rate: int = SAMPLE_RATE) -> bytes:
    n = int(dur * rate)
    return struct.pack(
        f"<{n}h", *[int(amp * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    )


def noise(dur: float, amp: int, rate: int = SAMPLE_RATE, seed: int = 0) -> bytes:
    n = int(dur * rate)
    return np.random.default_rng(seed).integers(-amp, amp, n).astype(np.int16).tobytes()


def real_speech() -> tuple[bytes, int]:
    with wave.open(SAMPLE_WAV, "rb") as w:
        raw = w.readframes(w.getnframes())
        mono = to_mono_int16(raw, w.getnchannels(), w.getsampwidth())
        return resample_int16(mono, w.getframerate(), SAMPLE_RATE), SAMPLE_RATE


# ---------------------------------------------------------------- audio

def test_audio() -> None:
    print("\naudio.py")
    pcm = sine(440, 1.0)
    check("duration_s", abs(duration_s(pcm) - 1.0) < 1e-6, f"{duration_s(pcm):.4f}s")

    w = pcm_to_wav(pcm)
    check("pcm_to_wav 헤더", w[:4] == b"RIFF" and w[8:12] == b"WAVE")
    with wave.open(__import__("io").BytesIO(w), "rb") as r:
        check(
            "pcm_to_wav 라운드트립",
            r.getframerate() == SAMPLE_RATE and r.getnchannels() == 1
            and r.readframes(r.getnframes()) == pcm,
        )

    t = tail(pcm, 0.25)
    check("tail 길이", abs(duration_s(t) - 0.25) < 1e-6, f"{duration_s(t):.4f}s")
    check("tail 끝 정렬", t == pcm[-len(t):])
    check("tail 초과 요청", tail(pcm, 99) == pcm)
    check("tail 짝수 바이트", len(tail(pcm, 0.3333)) % 2 == 0)

    up = resample_int16(sine(200, 1.0, rate=8000), 8000, 16000)
    check("resample 길이", abs(duration_s(up) - 1.0) < 0.01, f"{duration_s(up):.4f}s")
    check("resample 동일레이트 무변경", resample_int16(pcm, 16000, 16000) is pcm)

    stereo = struct.pack("<4h", 100, 300, -100, -300)
    check("to_mono_int16", to_mono_int16(stereo, 2, 2) == struct.pack("<2h", 200, -200))

    check("rms 무음", rms(bytes(640)) == 0.0)
    check("rms 빈입력", rms(b"") == 0.0)
    check("rms 사인파", abs(rms(sine(440, 0.1)) - 3000 / math.sqrt(2)) < 60,
          f"{rms(sine(440, 0.1)):.1f}")


# ---------------------------------------------------------------- vad

def test_vad() -> None:
    print("\nvad.py")
    s = Settings(base_url="x", token="y")
    v = EnergyVad(s.vad_speech_ratio, s.vad_abs_floor)

    quiet = bytes(640)
    for _ in range(60):
        v.is_speech(quiet)
    check("무음 → 비발화", v.is_speech(quiet)[0] is False)
    check("무음에서 floor 하한 유지", v.threshold >= s.vad_abs_floor,
          f"threshold={v.threshold:.1f}")

    loud = sine(300, 0.02, amp=8000)
    check("큰 신호 → 발화", v.is_speech(loud)[0] is True)

    # 발화 중에는 노이즈 플로어가 올라가면 안 된다. 긴 발화의 뒤쪽이 잘린다.
    before = v.noise_floor
    for _ in range(50):
        v.is_speech(loud)
    check("발화 중 floor 고정", v.noise_floor == before,
          f"{before:.1f} → {v.noise_floor:.1f}")


# ---------------------------------------------------------------- spectral

def test_spectral() -> None:
    print("\nspectral.py")
    s = Settings(base_url="x", token="y")
    args = (SAMPLE_RATE, s.max_flatness, s.min_flatness, s.min_voiced_frames)

    speech, _ = real_speech()
    ok, sc = is_speech_like(speech, *args)
    check("실제 발화 통과", ok, f"flatness={sc.flatness:.3f} band={sc.band_ratio:.3f}")

    for amp in (300, 900, 4000):
        ok, sc = is_speech_like(noise(2.0, amp), *args)
        check(f"백색잡음 amp={amp} 차단", not ok, f"flatness={sc.flatness:.3f}")

    for f in (60, 220):
        ok, sc = is_speech_like(sine(f, 2.0), *args)
        check(f"순음 {f}Hz 차단", not ok, f"flatness={sc.flatness:.4f}")

    ok, sc = is_speech_like(bytes(SAMPLE_RATE * 2), *args)
    check("무음 차단", not ok, f"voiced_frames={sc.voiced_frames}")

    ok, _ = is_speech_like(bytes(100), *args)
    check("짧은 입력 안전 처리", not ok)

    # 진폭을 키워도 판정이 뒤집히면 안 된다 (에너지 VAD 의 실패 지점).
    quiet = (np.frombuffer(speech, dtype=np.int16).astype(np.float64) * 0.2).astype(np.int16)
    ok, _ = is_speech_like(quiet.tobytes(), *args)
    check("발화 감쇠해도 통과", ok)

    sc_a = score(noise(1.0, 500, seed=1), SAMPLE_RATE)
    sc_b = score(noise(1.0, 5000, seed=1), SAMPLE_RATE)
    check("flatness 진폭 불변", abs(sc_a.flatness - sc_b.flatness) < 0.02,
          f"{sc_a.flatness:.4f} vs {sc_b.flatness:.4f}")

    # 회귀 방지: 발화 시작 직후의 짧은 창도 통과해야 한다.
    # band_ratio 로 자르던 때 여기서 실제 발화가 전부 차단됐고,
    # 잠정 결과 첫 표시가 1.4초에서 3.1초로 밀렸다.
    sil = bytes(int(0.3 * SAMPLE_RATE) * 2)
    for d in (0.3, 0.5, 0.9, 1.7):
        win = sil + speech[: int(d * SAMPLE_RATE) * 2]
        ok, sc = is_speech_like(win, *args)
        check(f"발화 시작 {d}s 창 통과", ok,
              f"flatness={sc.flatness:.3f} band={sc.band_ratio:.3f} voiced={sc.voiced_frames}")

    # 잡음은 짧아도 프레임만 충분하면 걸려야 한다.
    ok, sc = is_speech_like(noise(0.5, 900), *args)
    check("짧은 잡음 0.5s 차단", not ok,
          f"flatness={sc.flatness:.3f} voiced={sc.voiced_frames}")


def main() -> None:
    test_audio()
    test_vad()
    test_spectral()
    print(f"\n{'실패 없음' if not FAILURES else '실패: ' + ', '.join(FAILURES)}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
