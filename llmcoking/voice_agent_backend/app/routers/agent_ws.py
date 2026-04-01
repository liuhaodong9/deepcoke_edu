import asyncio
import json
import contextlib
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.state_manager import AgentSession

router = APIRouter()

@router.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    await websocket.accept()
    session = AgentSession(websocket)
    await session.send_state("idle")

    # Background workers
    vad_task = asyncio.create_task(session.vad_worker())
    tts_task = asyncio.create_task(session.tts_worker())

    try:
        while True:
            msg = await websocket.receive()
            if "text" in msg and msg["text"] is not None:
                # Control messages are JSON strings
                try:
                    payload = json.loads(msg["text"])
                except json.JSONDecodeError:
                    await session.send_error("Invalid JSON control message")
                    continue
                await session.handle_control(payload)
            elif "bytes" in msg and msg["bytes"] is not None:
                await session.handle_audio_bytes(msg["bytes"])
            else:
                await session.send_error("Unsupported WebSocket message")
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        for t in (vad_task, tts_task):
            t.cancel()
            with contextlib.suppress(Exception):
                await t
