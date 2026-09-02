"""RAG Suite Audio Transcription 클라이언트.

브라우저에서 직접 호출할 수 없어서 이 프록시가 필요하다.
probe.py [7] 에서 preflight 가 401 + Access-Control-* 헤더 없음으로 확인됐고,
애초에 kt_ 토큰을 프론트엔드에 두면 그대로 유출된다.
"""

import asyncio
import time
from dataclasses import dataclass

import httpx

from .audio import duration_s, pcm_to_wav
from .config import Settings


@dataclass
class Transcript:
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    seconds: float
    latency_s: float
    audio_s: float
    ok: bool = True
    error: str | None = None


class SttClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._sem = asyncio.Semaphore(settings.max_concurrent_requests)
        self._http = httpx.AsyncClient(
            timeout=settings.request_timeout_s,
            headers={"Authorization": f"Bearer {settings.token}"},
            limits=httpx.Limits(max_connections=settings.max_concurrent_requests * 2),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def transcribe(self, pcm: bytes, prompt: str = "") -> Transcript:
        audio_s = duration_s(pcm)
        data = {
            "model": self.s.model,
            "response_format": self.s.response_format,
            "language": self.s.language,
        }
        # 직전 확정 텍스트를 prompt 로 넘기면 문맥이 이어진다.
        # probe_quality.py 에서 3초 창 기준 CER 22.7% → 0.0% 로 떨어진 요인.
        if prompt:
            data["prompt"] = prompt[-200:]

        wav = pcm_to_wav(pcm)
        t0 = time.perf_counter()
        last_error = "unknown"

        # 파일 본문은 매 시도마다 새로 만들어 넘긴다. httpx 가 소비한 뒤에는 재사용이 안 된다.
        for attempt in range(self.s.max_retries + 1):
            async with self._sem:
                try:
                    r = await self._http.post(
                        f"{self.s.base_url}/v1/audio/transcriptions",
                        files={"file": ("chunk.wav", wav, "audio/wav")},
                        data=data,
                    )
                except Exception as exc:  # noqa: BLE001
                    last_error = repr(exc)
                    r = None

            if r is not None and r.status_code == 200:
                break
            if r is not None:
                last_error = f"HTTP {r.status_code}: {r.text[:200]}"
                # 4xx 는 요청 자체가 잘못된 것이라 다시 보내도 같다.
                if r.status_code < 500:
                    return Transcript("", 0, 0, 0, 0.0, time.perf_counter() - t0, audio_s,
                                      ok=False, error=last_error)
            if attempt < self.s.max_retries:
                await asyncio.sleep(self.s.retry_backoff_s * (attempt + 1))
        else:
            return Transcript("", 0, 0, 0, 0.0, time.perf_counter() - t0, audio_s,
                              ok=False, error=f"{self.s.max_retries + 1}회 시도 실패 — {last_error}")

        latency = time.perf_counter() - t0

        body = r.json()
        usage = body.get("usage") or {}
        return Transcript(
            text=(body.get("text") or "").strip(),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            seconds=usage.get("seconds", 0),
            latency_s=latency,
            audio_s=audio_s,
        )
