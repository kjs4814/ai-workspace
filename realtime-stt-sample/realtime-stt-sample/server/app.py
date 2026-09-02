"""FastAPI 서버. 정적 페이지 + WebSocket 오디오 스트림.

프로토콜
  client → server   binary : 16kHz mono int16 raw PCM
                    text   : {"type":"start"} | {"type":"stop"} | {"type":"config", ...}
  server → client   text   : {"type":"vad"|"interim"|"final"|"dropped"|"error"|"ready"|"done", ...}
"""

import dataclasses
import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .config import FRAME_MS, SAMPLE_RATE, Settings
from .session import Session
from .stt import SttClient

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

settings = Settings.from_env()
stt = SttClient(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await stt.aclose()


app = FastAPI(title="RAG Suite 실시간 STT 샘플", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


COOKIE = "stt_access"


def _key_ok(supplied: str | None) -> bool:
    """APP_ACCESS_KEY 가 비어 있으면 게이트 자체를 끈다(로컬 전용)."""
    if not settings.access_key:
        return True
    return bool(supplied) and hmac.compare_digest(supplied, settings.access_key)


@app.get("/")
async def index(request: Request) -> Response:
    if not settings.access_key:
        return FileResponse(WEB_DIR / "index.html")

    # ?key=... 로 한 번 들어오면 쿠키에 담아두고 이후에는 쿠키로 통과시킨다.
    supplied = request.query_params.get("key") or request.cookies.get(COOKIE)
    if not _key_ok(supplied):
        return PlainTextResponse("접근 키가 필요합니다. ?key=... 를 붙여 접속하세요.", status_code=401)

    resp = FileResponse(WEB_DIR / "index.html")
    # 터널/배포는 HTTPS 로 뜨므로 그때는 secure 를 켠다.
    # localhost 평문 접속에서 secure 를 켜면 쿠키가 저장되지 않는다.
    resp.set_cookie(
        COOKIE,
        supplied,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=86400,
    )
    return resp


@app.get("/api/config")
async def api_config() -> dict:
    return {
        "sample_rate": SAMPLE_RATE,
        "frame_ms": FRAME_MS,
        "model": settings.model,
        "language": settings.language,
        "interim_enabled": settings.interim_enabled,
        "interim_min_interval_s": settings.interim_min_interval_s,
        "vad_end_silence_ms": settings.vad_end_silence_ms,
        "max_utterance_s": settings.max_utterance_s,
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    # 페이지만 막아봐야 소용없다. WebSocket 이 실제로 토큰을 쓰는 경로다.
    if not _key_ok(ws.query_params.get("key") or ws.cookies.get(COOKIE)):
        await ws.close(code=4401, reason="접근 키가 필요합니다")
        return
    await ws.accept()

    async def emit(event: dict) -> None:
        try:
            await ws.send_text(json.dumps(event, ensure_ascii=False))
        except (WebSocketDisconnect, RuntimeError):
            pass

    # 연결마다 설정 사본을 준다. 공유하면 한 클라이언트의 토글이 전체에 영향을 준다.
    session = Session(stt, dataclasses.replace(settings), emit)
    await emit({"type": "ready", "sample_rate": SAMPLE_RATE, "frame_ms": FRAME_MS})

    async def handle_command(text: str) -> None:
        cmd = json.loads(text)
        kind = cmd.get("type")
        if kind == "stop":
            await session.flush()
            await emit(
                {
                    "type": "done",
                    "transcript": session.transcript,
                    "stats": session.stats.snapshot(session.s),
                }
            )
        elif kind == "config" and "interim" in cmd:
            session.s.interim_enabled = bool(cmd["interim"])

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if (data := msg.get("bytes")) is not None:
                cap = session.s.max_session_tokens
                if cap and session.stats.total_tokens >= cap:
                    # 공유 링크로 열어둔 서버가 무한정 토큰을 태우지 않게 막는다.
                    await emit(
                        {"type": "error", "where": "quota",
                         "message": f"이 연결의 토큰 상한 {cap:,} 에 도달했습니다. "
                                    "새로고침하면 다시 시작합니다."}
                    )
                    await ws.close(code=4429, reason="token quota exceeded")
                    break
                await session.feed(data)
            elif (text := msg.get("text")) is not None:
                await handle_command(text)
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
