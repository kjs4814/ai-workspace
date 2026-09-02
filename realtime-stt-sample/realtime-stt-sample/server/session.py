"""실시간 전사 상태 머신.

두 경로를 동시에 돌린다.

  잠정(interim)  발화 시작부터 지금까지 누적한 오디오를 주기적으로 재전사한다.
                 growing window 방식. 화면을 즉시 갱신하는 용도이고 언제든 뒤집힌다.
  확정(final)    VAD 가 발화 끝을 잡으면 발화 전체를 직전 확정 텍스트와 함께 전사한다.
                 probe_quality.py 에서 CER 0.0% 가 나온 경로.

고정 시간 분할을 쓰지 않는 이유는 실측 때문이다. 1초 고정 분할 CER 68.2%,
2초 22.7%. 단어 중간이 잘리면 whisper 가 없는 말을 만들어낸다.
VAD 로 무음 경계에서 자르면 이 문제가 사라진다.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

from .audio import duration_s, tail
from .config import FRAME_BYTES, FRAME_MS, SAMPLE_RATE, SAMPLE_WIDTH, Settings
from .spectral import SpectralScore, is_speech_like
from .stt import SttClient, Transcript
from .vad import EnergyVad


@dataclass
class Stats:
    final_calls: int = 0
    interim_calls: int = 0
    failed_calls: int = 0
    dropped_segments: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # growing window 잠정 전사가 추가로 쓴 몫. 확정 경로만 돌렸을 때와 비교하기 위해 나눠 센다.
    final_tokens: int = 0
    interim_tokens: int = 0
    audio_sent_s: float = 0.0
    latencies: list[float] = field(default_factory=list)

    def krw(self, s: Settings) -> float:
        return (
            self.prompt_tokens * s.krw_per_1m_input
            + self.completion_tokens * s.krw_per_1m_output
        ) / 1_000_000

    def snapshot(self, s: Settings) -> dict:
        lat = sorted(self.latencies)
        return {
            "final_calls": self.final_calls,
            "interim_calls": self.interim_calls,
            "failed_calls": self.failed_calls,
            "dropped_segments": self.dropped_segments,
            "total_tokens": self.total_tokens,
            "final_tokens": self.final_tokens,
            "interim_tokens": self.interim_tokens,
            # 잠정 표시를 껐을 때 대비 몇 배를 쓰고 있는지.
            "interim_multiplier": (
                round(self.total_tokens / self.final_tokens, 2) if self.final_tokens else 0
            ),
            "audio_sent_s": round(self.audio_sent_s, 2),
            "krw": round(self.krw(s), 4),
            "latency_avg_ms": round(1000 * sum(lat) / len(lat)) if lat else 0,
            "latency_p95_ms": round(1000 * lat[int(len(lat) * 0.95)]) if lat else 0,
        }


class Session:
    """WebSocket 연결 1개당 1 인스턴스."""

    def __init__(self, stt: SttClient, settings: Settings, emit):
        self.stt = stt
        self.s = settings
        self.emit = emit  # async callable(dict)

        self._vad = EnergyVad(settings.vad_speech_ratio, settings.vad_abs_floor)
        self._residual = b""
        self._preroll: deque[bytes] = deque(
            maxlen=max(1, settings.vad_preroll_ms // FRAME_MS)
        )

        self._utt = bytearray()
        self._in_speech = False
        self._speech_run = 0
        self._sil_run_ms = 0
        self._utt_id = 0

        self._committed = ""
        self._interim_task: asyncio.Task | None = None
        self._interim_last = 0.0

        self.stats = Stats()
        self._final_q: asyncio.Queue = asyncio.Queue()
        self._final_busy = False
        self._final_worker = asyncio.create_task(self._run_finals())
        # create_task 의 반환값을 잡아두지 않으면 실행 도중 GC 될 수 있다.
        self._bg: set[asyncio.Task] = set()
        self._closed = False

    # ------------------------------------------------------------ 입력

    async def feed(self, pcm: bytes) -> None:
        """브라우저에서 온 16kHz mono int16 raw PCM."""
        data = self._residual + pcm
        n = len(data) // FRAME_BYTES
        for i in range(n):
            self._on_frame(data[i * FRAME_BYTES : (i + 1) * FRAME_BYTES])
        self._residual = data[n * FRAME_BYTES :]
        self._maybe_interim()

    def _on_frame(self, frame: bytes) -> None:
        speech, _level = self._vad.is_speech(frame)

        if not self._in_speech:
            self._preroll.append(frame)
            if speech:
                self._speech_run += 1
                if self._speech_run >= self.s.vad_start_frames:
                    self._start_utterance()
            else:
                self._speech_run = 0
            return

        self._utt += frame
        if speech:
            self._sil_run_ms = 0
        else:
            self._sil_run_ms += FRAME_MS
            if self._sil_run_ms >= self.s.vad_end_silence_ms:
                self._finalize("silence")
                return
        if duration_s(self._utt) >= self.s.max_utterance_s:
            self._finalize("maxlen")

    def _start_utterance(self) -> None:
        # preroll 을 앞에 붙여 첫 음절이 잘리지 않게 한다.
        self._utt = bytearray(b"".join(self._preroll))
        self._preroll.clear()
        self._in_speech = True
        self._speech_run = 0
        self._sil_run_ms = 0
        self._utt_id += 1
        self._interim_last = 0.0
        self._schedule(self.emit({"type": "vad", "state": "speech", "utt": self._utt_id}))

    def _finalize(self, reason: str) -> None:
        pcm = bytes(self._utt)
        utt_id = self._utt_id
        # 발화 끝에 붙은 무음은 잘라낸다. 그대로 두면 매 발화마다
        # vad_end_silence_ms 만큼을 초당 107 토큰으로 사서 보내는 셈이 된다.
        excess_ms = self._sil_run_ms - self.s.trailing_silence_keep_ms
        if excess_ms > 0:
            cut = int(excess_ms / 1000 * SAMPLE_RATE) * SAMPLE_WIDTH
            pcm = pcm[: max(0, len(pcm) - cut)]

        self._utt = bytearray()
        self._in_speech = False
        self._speech_run = 0
        self._sil_run_ms = 0

        # 진행 중이던 잠정 전사는 확정본이 대체하므로 버린다.
        if self._interim_task and not self._interim_task.done():
            self._interim_task.cancel()

        self._schedule(self.emit({"type": "vad", "state": "idle", "utt": utt_id}))

        if duration_s(pcm) * 1000 < self.s.min_utterance_ms:
            self.stats.dropped_segments += 1
            return
        self._final_q.put_nowait((utt_id, pcm, reason))

    # ------------------------------------------------------------ 확정 경로

    async def _run_finals(self) -> None:
        """순서 보장을 위해 직렬로 처리한다. prompt 체인이 순서에 의존한다."""
        while True:
            utt_id, pcm, reason = await self._final_q.get()
            self._final_busy = True
            try:
                ok_audio, sc = self._gate(pcm)
                if not ok_audio:
                    # API 호출 자체를 하지 않는다. 잡음을 보내면 요금도 나가고
                    # ' 감사합니다.' 같은 degenerate 출력이 확정 텍스트로 들어간다.
                    self.stats.dropped_segments += 1
                    await self.emit(
                        {"type": "dropped", "utt": utt_id, "reason": "noise-gate",
                         "audio_s": round(duration_s(pcm), 2), **sc.as_dict()}
                    )
                    continue

                t = await self.stt.transcribe(pcm, prompt=self._committed)
                self._account(t, interim=False)
                if not t.ok:
                    await self.emit({"type": "error", "where": "final", "message": t.error})
                    continue
                if not t.text:
                    continue
                self._committed = (self._committed + " " + t.text).strip()
                await self.emit(
                    {
                        "type": "final",
                        "utt": utt_id,
                        "text": t.text,
                        "reason": reason,
                        "audio_s": round(t.audio_s, 2),
                        "tokens": t.total_tokens,
                        "latency_ms": round(t.latency_s * 1000),
                        "stats": self.stats.snapshot(self.s),
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                await self.emit({"type": "error", "where": "final", "message": repr(exc)})
            finally:
                self._final_busy = False

    def _gate(self, pcm: bytes) -> tuple[bool, SpectralScore]:
        """잡음 구간을 API 로 보내기 전에 걸러낸다."""
        if not self.s.noise_gate_enabled:
            return True, SpectralScore(0.0, 0.0, 0)
        return is_speech_like(
            pcm,
            SAMPLE_RATE,
            self.s.max_flatness,
            self.s.min_flatness,
            self.s.min_voiced_frames,
        )

    # ------------------------------------------------------------ 잠정 경로

    def _maybe_interim(self) -> None:
        if not self.s.interim_enabled or not self._in_speech or self._closed:
            return
        if self._interim_task and not self._interim_task.done():
            return  # single-flight: 앞 요청이 끝나야 다음을 쏜다
        now = time.monotonic()
        if now - self._interim_last < self.s.interim_min_interval_s:
            return
        snapshot = bytes(self._utt)
        if duration_s(snapshot) < 0.4:
            return
        self._interim_last = now
        self._interim_task = asyncio.create_task(
            self._do_interim(snapshot, self._utt_id)
        )

    async def _do_interim(self, pcm: bytes, utt_id: int) -> None:
        try:
            window = tail(pcm, self.s.interim_max_window_s)
            ok_audio, _ = self._gate(window)
            if not ok_audio:
                return
            t = await self.stt.transcribe(window, prompt=self._committed)
            self._account(t, interim=True)
            if not t.ok:
                # 잠정 실패는 치명적이지 않다. 곧 다음 잠정이나 확정본이 덮는다.
                # 그래도 조용히 삼키면 왜 화면이 안 갱신되는지 알 수 없어 알려준다.
                await self.emit(
                    {"type": "warn", "where": "interim", "message": t.error}
                )
                return
            # 응답이 오는 사이 발화가 끝났거나 다음 발화로 넘어갔으면 버린다.
            if utt_id != self._utt_id or not self._in_speech:
                return
            if not t.text:
                return
            await self.emit(
                {
                    "type": "interim",
                    "utt": utt_id,
                    "text": t.text,
                    "audio_s": round(t.audio_s, 2),
                    "tokens": t.total_tokens,
                    "latency_ms": round(t.latency_s * 1000),
                    "stats": self.stats.snapshot(self.s),
                }
            )
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------ 기타

    def _account(self, t: Transcript, interim: bool) -> None:
        if interim:
            self.stats.interim_calls += 1
        else:
            self.stats.final_calls += 1
        if not t.ok:
            self.stats.failed_calls += 1
            return
        self.stats.prompt_tokens += t.prompt_tokens
        self.stats.completion_tokens += t.completion_tokens
        self.stats.total_tokens += t.total_tokens
        if interim:
            self.stats.interim_tokens += t.total_tokens
        else:
            self.stats.final_tokens += t.total_tokens
        self.stats.audio_sent_s += t.audio_s
        self.stats.latencies.append(t.latency_s)

    def _schedule(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def flush(self, timeout_s: float = 15.0) -> None:
        """녹음 정지 시 남은 발화를 확정하고 처리 중인 것까지 끝나기를 기다린다."""
        if self._in_speech:
            self._finalize("stop")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._final_q.empty() and not self._final_busy:
                return
            await asyncio.sleep(0.05)

    async def close(self) -> None:
        self._closed = True
        if self._interim_task and not self._interim_task.done():
            self._interim_task.cancel()
        self._final_worker.cancel()
        try:
            await self._final_worker
        except asyncio.CancelledError:
            pass

    @property
    def transcript(self) -> str:
        return self._committed
