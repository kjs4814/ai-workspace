"""에너지 기반 VAD.

무음을 서버로도 API 로도 보내지 않는 것이 목적이다. probe_threshold.py 에서
무음/험/백색잡음 전부 " 감사합니다." 를 반환했고 초당 107 토큰이 그대로 과금됐다.
avg_logprob 은 실제 발화와 값이 겹쳐 사후 필터로 쓸 수 없으므로, 사전 게이팅이 주 방어선이다.

Silero VAD 같은 신경망 VAD 가 잡음 환경에서 더 정확하다. 여기서는 의존성 없이
동작하도록 적응형 노이즈 플로어 방식으로 구현했다.
"""

from .audio import rms


class EnergyVad:
    def __init__(self, speech_ratio: float, abs_floor: float):
        self.speech_ratio = speech_ratio
        self.abs_floor = abs_floor
        self.noise_floor = abs_floor
        self._warmup = 0

    @property
    def threshold(self) -> float:
        return max(self.noise_floor * self.speech_ratio, self.abs_floor)

    def is_speech(self, frame: bytes) -> tuple[bool, float]:
        """프레임 하나를 판정하고 (발화여부, RMS) 를 반환한다."""
        level = rms(frame)
        speech = level > self.threshold

        # 노이즈 플로어는 무음 구간에서만 갱신한다. 발화 중에 올리면
        # 긴 발화의 뒤쪽이 통째로 무음으로 오판된다.
        if not speech:
            # 초반 몇 프레임은 빠르게 수렴시키고 이후 천천히 따라가게 한다.
            alpha = 0.3 if self._warmup < 25 else 0.02
            self.noise_floor = (1 - alpha) * self.noise_floor + alpha * level
            self._warmup += 1

        return speech, level
