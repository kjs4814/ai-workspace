"""PCM ↔ WAV 변환.

브라우저가 16kHz mono int16 raw PCM 을 보내오고, 서버는 구간마다 헤더를 붙여
독립 재생 가능한 WAV 로 만들어 업로드한다. 이 방식이면 ffmpeg 가 필요 없다.
(MediaRecorder 의 webm 은 두 번째 chunk 부터 헤더가 없어 단독 디코딩이 안 된다.)
"""

import array
import io
import math
import wave

from .config import SAMPLE_RATE, SAMPLE_WIDTH


def pcm_to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def duration_s(pcm: bytes, rate: int = SAMPLE_RATE) -> float:
    return len(pcm) / (rate * SAMPLE_WIDTH)


def rms(frame: bytes) -> float:
    """int16 프레임의 RMS. 빈 프레임은 0."""
    if not frame:
        return 0.0
    a = array.array("h")
    a.frombytes(frame[: len(frame) // 2 * 2])
    if not a:
        return 0.0
    return math.sqrt(sum(v * v for v in a) / len(a))


def resample_int16(pcm: bytes, src_rate: int, dst_rate: int = SAMPLE_RATE) -> bytes:
    """선형 보간 리샘플. 시뮬레이터/파일 입력용.

    브라우저 경로는 AudioWorklet 이 같은 일을 하므로 여기를 거치지 않는다.
    """
    if src_rate == dst_rate:
        return pcm
    src = array.array("h")
    src.frombytes(pcm[: len(pcm) // 2 * 2])
    n_out = int(len(src) * dst_rate / src_rate)
    step = src_rate / dst_rate
    out = array.array("h", bytes(2 * n_out))
    for i in range(n_out):
        pos = i * step
        j = int(pos)
        frac = pos - j
        a = src[j]
        b = src[j + 1] if j + 1 < len(src) else a
        out[i] = int(a + (b - a) * frac)
    return out.tobytes()


def to_mono_int16(pcm: bytes, channels: int, sampwidth: int) -> bytes:
    """다채널/8bit 입력을 mono int16 으로 정규화한다."""
    if sampwidth != 2:
        raise ValueError(f"16bit PCM 만 지원합니다 (sampwidth={sampwidth})")
    if channels == 1:
        return pcm
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) // (2 * channels) * 2 * channels])
    out = array.array("h", bytes(2 * (len(a) // channels)))
    for i in range(len(out)):
        out[i] = sum(a[i * channels : (i + 1) * channels]) // channels
    return out.tobytes()


def tail(pcm: bytes, seconds: float, rate: int = SAMPLE_RATE) -> bytes:
    """뒤에서 seconds 만큼 잘라낸다. 프레임 경계에 맞춘다."""
    n = int(seconds * rate) * SAMPLE_WIDTH
    if n >= len(pcm):
        return pcm
    off = len(pcm) - n
    return pcm[off - (off % SAMPLE_WIDTH):]
