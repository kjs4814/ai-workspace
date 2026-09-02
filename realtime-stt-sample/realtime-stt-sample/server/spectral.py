"""발화 구간이 사람 목소리인지 잡음인지 오디오만으로 판별한다.

에너지 VAD 는 큰 잡음을 발화로 오판한다. 실제로 잡음 버스트를 흘려보내면
whisper 가 ' 감사합니다.' 를 반환하고 그대로 확정 텍스트가 됐다.

텍스트 패턴 차단(blocklist)은 쓰지 않는다. 사용자가 정말로 "감사합니다" 라고
말했을 때 구분할 방법이 없고, verbose_json 의 compression_ratio 는 텍스트만의
함수라 같은 문자열이면 항상 같은 값이 나와 판별에 쓸 수 없다.

판정은 spectral flatness(기하평균/산술평균) 하나로 한다. 진폭과 무관하고
창 길이가 짧아도 값이 흔들리지 않는다.

  발화        0.17 ~ 0.22   (0.6초 창부터 7.7초 창까지 안정적)
  백색잡음    0.85          (진폭 300 ~ 4000 에서 동일)
  순음/험     0.001         (harmonic 이 하나뿐이라 오히려 극단적으로 낮다)

그래서 상한만이 아니라 하한도 둔다. 위로는 잡음, 아래로는 순음을 자른다.

speech-band ratio(300~3400Hz 에너지 비율)는 판정에서 뺐다. 긴 발화는 0.61 로
잘 나오지만 발화 시작 직후 짧은 창에서는 0.30~0.44 까지 떨어져 백색잡음(0.38)과
겹친다. 이 값으로 자르면 짧은 실제 발화를 버리게 된다. 지표로는 계속 보고한다.

프레임 수가 부족해 판단이 서지 않으면 통과시킨다(fail-open). 실제 발화를
버리는 쪽이 잡음 한 조각을 통과시키는 쪽보다 나쁘다. 길이가 있는 잡음은
프레임이 충분하므로 어차피 걸린다.
"""

from dataclasses import dataclass

import numpy as np

FRAME = 512
HOP = 256
_WINDOW = np.hanning(FRAME)


@dataclass
class SpectralScore:
    flatness: float
    band_ratio: float
    voiced_frames: int

    def as_dict(self) -> dict:
        return {
            "flatness": round(self.flatness, 4),
            "band_ratio": round(self.band_ratio, 4),
            "voiced_frames": self.voiced_frames,
        }


def score(pcm: bytes, rate: int, frame_rms_floor: float = 50.0) -> SpectralScore:
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if len(x) < FRAME:
        return SpectralScore(0.0, 0.0, 0)

    n = 1 + (len(x) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * _WINDOW

    # 프레임별 RMS 로 조용한 프레임을 뺀다. 무음이 섞이면 지표가 흐려진다.
    keep = np.sqrt((frames ** 2).mean(axis=1)) >= frame_rms_floor
    if not keep.any():
        return SpectralScore(0.0, 0.0, 0)
    frames = frames[keep]

    spec = np.abs(np.fft.rfft(frames, axis=1))
    mag = spec[:, 1:] + 1e-10  # DC 성분 제외
    flatness = np.median(np.exp(np.log(mag).mean(axis=1)) / mag.mean(axis=1))

    freqs = np.fft.rfftfreq(FRAME, 1 / rate)
    band = (freqs >= 300) & (freqs <= 3400)
    power = spec ** 2
    ratio = np.median(power[:, band].sum(axis=1) / (power.sum(axis=1) + 1e-10))

    return SpectralScore(float(flatness), float(ratio), int(keep.sum()))


def is_speech_like(
    pcm: bytes,
    rate: int,
    max_flatness: float,
    min_flatness: float,
    min_voiced_frames: int,
) -> tuple[bool, SpectralScore]:
    s = score(pcm, rate)
    if s.voiced_frames == 0:
        return False, s  # 전부 무음. 보낼 이유가 없다.
    if s.voiced_frames < min_voiced_frames:
        return True, s  # 판단 불가 → 통과
    return (min_flatness <= s.flatness <= max_flatness), s
