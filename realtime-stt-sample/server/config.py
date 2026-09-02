"""설정값. 기본값은 probe.py / probe_quality.py / probe_threshold.py 실측 결과에서 나왔다."""

import os
from dataclasses import dataclass

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH

# 참고: 무음/잡음을 그대로 올리면 whisper-large-v3 는 길이와 무관하게
# ' 감사합니다.' 를 반환한다(probe_threshold.py 에서 재현).
# 이 출력을 사후에 걸러내려는 시도는 두 번 실패했다.
#   avg_logprob        발화 최저 -0.453 < 무음 -0.430 으로 값이 겹쳐 판별 불가
#   compression_ratio  텍스트만의 함수라 같은 문자열이면 항상 같은 값
# 그래서 방어선은 전부 오디오 쪽에 둔다. vad.py(에너지) + spectral.py(음색).


@dataclass
class Settings:
    base_url: str
    token: str
    model: str = "openai/whisper-large-v3"
    language: str = "ko"

    # --- VAD -------------------------------------------------------------
    # 적응형 노이즈 플로어 대비 배수. 낮추면 민감, 높이면 둔감.
    vad_speech_ratio: float = 3.0
    # 완전 무음 환경에서 노이즈 플로어가 0 으로 붕괴하는 것을 막는 하한 (int16 RMS).
    vad_abs_floor: float = 120.0
    # 발화 시작으로 인정할 연속 speech 프레임 수 (20ms * 3 = 60ms).
    vad_start_frames: int = 3
    # 발화 종료로 인정할 무음 길이. 짧으면 문장이 토막나고 길면 확정이 늦어진다.
    vad_end_silence_ms: int = 600
    # 발화 시작 앞쪽을 함께 보내 첫 음절 잘림을 막는다.
    vad_preroll_ms: int = 300
    # 이 길이를 넘으면 강제 확정. prompt 로 문맥이 이어지므로 정확도 손실은 작다.
    max_utterance_s: float = 12.0
    # 이보다 짧은 발화는 버린다 (기침, 클릭음).
    min_utterance_ms: int = 300
    # 발화 끝 무음을 얼마나 남기고 잘라낼지. 확정 전 이 이상은 잘라 비용과 패딩을 줄인다.
    trailing_silence_keep_ms: int = 150

    # --- 잡음 게이트 (spectral.py) ---------------------------------------
    # 측정값: 발화 0.17~0.22 / 백색잡음 0.85 / 순음·험 0.001.
    # 위로는 잡음, 아래로는 순음을 자른다. band_ratio 는 짧은 발화에서 잡음과
    # 겹쳐 판정에 쓰지 않는다(spectral.py 주석 참고).
    noise_gate_enabled: bool = True
    max_flatness: float = 0.45
    min_flatness: float = 0.02
    # 이보다 유성 프레임이 적으면 판단을 보류하고 통과시킨다.
    min_voiced_frames: int = 12

    # --- growing window (잠정 결과) --------------------------------------
    interim_enabled: bool = True
    # 잠정 전사 최소 간격. 호출은 single-flight 라 실제 간격은 이보다 길어질 수 있다.
    interim_min_interval_s: float = 0.8
    # 잠정 전사에 쓸 최대 창 길이. 발화가 길어져도 비용이 선형 이상으로 늘지 않게 자른다.
    interim_max_window_s: float = 12.0

    # --- 과금 표시 -------------------------------------------------------
    # response_format=json 은 usage 를 주지만 타임스탬프가 없고,
    # verbose_json 은 그 반대다(probe.py [2] 참고). 정확한 usage 를 택했다.
    response_format: str = "json"
    # 문서상 Input 30원 / Output 610원. 단위(1M/1K 토큰) 미확인이라 1M 기준으로 가정했다.
    krw_per_1m_input: float = 30.0
    krw_per_1m_output: float = 610.0

    request_timeout_s: float = 30.0
    max_concurrent_requests: int = 8
    # 프록시가 간헐적으로 502 를 낸다. 27회 연속 호출에 1회꼴로 관측됐다.
    # 5xx 와 연결 오류만 재시도한다. 4xx 는 재시도해도 같은 결과다.
    max_retries: int = 2
    retry_backoff_s: float = 0.15

    # --- 공유할 때 필요한 것 ---------------------------------------------
    # 이 서버는 자기 RAG_SUITE_TOKEN 으로 API 를 호출한다. 주소를 아는 사람은
    # 누구나 그 토큰을 태울 수 있다는 뜻이다. 터널이나 배포로 외부에 노출한다면
    # 아래 둘을 반드시 켜라. localhost 전용이면 없어도 된다.
    #
    # 접근 키. 설정하면 ?key=... 없이는 페이지도 WebSocket 도 열리지 않는다.
    access_key: str = ""
    # 연결 1개가 쓸 수 있는 토큰 상한. 넘으면 그 연결의 전사를 멈춘다.
    # 0 이면 무제한. 실측 기준 1분 발화가 대략 6,400 토큰(잠정 표시 켠 상태).
    max_session_tokens: int = 0

    @classmethod
    def from_env(cls) -> "Settings":
        base = os.environ.get("RAG_SUITE_BASE_URL", "").rstrip("/")
        token = os.environ.get("RAG_SUITE_TOKEN", "")
        if not base or not token:
            raise SystemExit(
                "\nRAG_SUITE_BASE_URL / RAG_SUITE_TOKEN 이 설정되지 않았습니다.\n\n"
                "  cp .env.example .env    그리고 두 값을 채운 뒤\n"
                "  ./run.sh\n\n"
                "토큰은 kt cloud RAG Suite 콘솔에서 발급받습니다.\n"
            )
        return cls(
            base_url=base,
            token=token,
            language=os.environ.get("STT_LANGUAGE", "ko"),
            interim_enabled=os.environ.get("STT_INTERIM", "1") != "0",
            access_key=os.environ.get("APP_ACCESS_KEY", ""),
            max_session_tokens=int(os.environ.get("MAX_SESSION_TOKENS", "0")),
        )
