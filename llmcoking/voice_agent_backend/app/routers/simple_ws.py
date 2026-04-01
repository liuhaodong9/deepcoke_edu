"""
Simple voice WebSocket: browser PCM stream -> realtime ASR -> LLM -> TTS.
This router enforces and reports a recommended realtime audio profile.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.services.asr_postprocess import ASRTextPostProcessor
from app.services.asr_service import WhisperASR
from app.services.deepseek_service import deepseek_stream_chat, split_into_sentences
from app.services.term_postprocess import TermPostProcessor
from app.services.tts_service import SparkTTSCLI, b64encode_wav

logger = logging.getLogger("simple-voice")
router = APIRouter()


class SimpleSession:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self._loop = asyncio.get_running_loop()
        self._asr = WhisperASR()
        glossary_dir = str((__import__("pathlib").Path(__file__).resolve().parents[3] / "glossary"))
        self._asr_post = ASRTextPostProcessor(glossary_dir=glossary_dir)
        self._post = TermPostProcessor(glossary_dir=glossary_dir)
        self._tts = SparkTTSCLI()
        self._closed = False
        self._cancel = asyncio.Event()
        self._llm_task: asyncio.Task | None = None
        self._tts_q: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        self._sentence_id = 0

        # Conversation history
        self._history: list[dict] = []
        self._max_history_turns = 20

        # Streaming ASR state
        self._stream_session = None
        self._session_ready = False
        self._pending_audio: list[np.ndarray] = []
        self._in_speech = False
        self._speech_buf: list[np.ndarray] = []
        self._domain_hint = "焦化 炼焦 焦炭 煤焦油 配煤 高炉 焦炉 干熄焦 煤化工"

        # Recommended audio profile for realtime ASR
        self.sample_rate_hz = max(8000, int(getattr(settings, "SIMPLE_AUDIO_SAMPLE_RATE", 16000)))
        self.channels = max(1, int(getattr(settings, "SIMPLE_AUDIO_CHANNELS", 1)))
        bits_raw = int(getattr(settings, "SIMPLE_AUDIO_BITS_PER_SAMPLE", 16))
        self.bits_per_sample = 16 if bits_raw not in {8, 16, 24, 32} else bits_raw
        self.frame_ms = max(20, min(100, int(getattr(settings, "SIMPLE_AUDIO_FRAME_MS", 40))))
        self.frame_samples = max(160, int(self.sample_rate_hz * self.frame_ms / 1000))
        self.frame_bytes = int(self.frame_samples * self.channels * (self.bits_per_sample // 8))
        self.nominal_bitrate_bps = int(self.sample_rate_hz * self.channels * self.bits_per_sample)

        # Accept some variation in inbound frame size, but track mismatch ratio.
        self.min_frame_bytes = max(2, self.frame_bytes // 3)
        self.max_frame_bytes = max(self.frame_bytes * 3, 4096)

        self._client_audio_profile: dict = {}
        self._profile_warn_sent = False

        self._rx_frame_count = 0
        self._rx_bad_frame_count = 0
        self._rx_bytes_total = 0
        self._rx_last_frame_bytes = 0
        self._last_audio_debug_ts = 0.0

    def _upstream_asr_transport(self) -> str:
        provider = str(getattr(self._asr, "provider", "")).strip().lower()
        if provider in {"doubao_rtasr", "xfyun_rtasr"}:
            return "websocket"
        return "http"

    def _server_audio_profile(self) -> dict:
        return {
            "encoding": "pcm_s16le" if self.bits_per_sample == 16 else "pcm",
            "sample_rate_hz": int(self.sample_rate_hz),
            "channels": int(self.channels),
            "bits_per_sample": int(self.bits_per_sample),
            "frame_ms": int(self.frame_ms),
            "frame_samples": int(self.frame_samples),
            "frame_bytes": int(self.frame_bytes),
            "bitrate_bps": int(self.nominal_bitrate_bps),
            "transport": "websocket",
            "upstream_asr_transport": self._upstream_asr_transport(),
        }

    async def send_audio_profile(self):
        await self.send({"type": "audio_profile", **self._server_audio_profile()})

    async def check_and_report_audio_profile(self):
        prof = self._client_audio_profile if isinstance(self._client_audio_profile, dict) else {}
        if not prof:
            if not self._profile_warn_sent:
                self._profile_warn_sent = True
                await self.send({
                    "type": "audio_profile_check",
                    "ok": False,
                    "warnings": ["missing_client_audio_profile"],
                    "server": self._server_audio_profile(),
                })
            return

        warnings: list[str] = []
        enc = str(prof.get("encoding") or "").lower().strip()
        if enc and ("pcm" not in enc):
            warnings.append("encoding_not_pcm")

        sr = int(prof.get("sample_rate") or prof.get("sample_rate_hz") or 0)
        ch = int(prof.get("channels") or 0)
        bits = int(prof.get("bits_per_sample") or 0)
        fms = int(prof.get("frame_ms") or 0)

        if sr and sr != self.sample_rate_hz:
            warnings.append(f"sample_rate_mismatch:{sr}!={self.sample_rate_hz}")
        if ch and ch != self.channels:
            warnings.append(f"channels_mismatch:{ch}!={self.channels}")
        if bits and bits != self.bits_per_sample:
            warnings.append(f"bits_per_sample_mismatch:{bits}!={self.bits_per_sample}")
        if fms and abs(fms - self.frame_ms) > 20:
            warnings.append(f"frame_ms_far_from_recommend:{fms}!~{self.frame_ms}")

        await self.send({
            "type": "audio_profile_check",
            "ok": len(warnings) == 0,
            "warnings": warnings,
            "client": prof,
            "server": self._server_audio_profile(),
        })

    async def send(self, obj: dict):
        if self._closed:
            return
        await self.ws.send_text(json.dumps(obj, ensure_ascii=False))

    def _asr_context_text(self) -> str:
        parts: list[str] = [self._domain_hint]
        for item in self._history[-8:]:
            if not isinstance(item, dict):
                continue
            txt = str(item.get("content") or "").strip()
            if txt:
                parts.append(txt[:200])
        return " ".join(parts)

    # ---- Streaming ASR ----
    async def start_stream_asr(self):
        if self._stream_session is not None or self._session_ready:
            return
        if not (self._asr.doubao_rt and self._asr.doubao_rt.enabled):
            return

        self._pending_audio.clear()
        loop = self._loop

        def _on_partial(text: str):
            if self._closed or self._cancel.is_set():
                return
            cleaned = self._asr_post(text, context=self._asr_context_text(), is_partial=True).strip()
            if cleaned:
                asyncio.run_coroutine_threadsafe(
                    self.send({"type": "asr_partial", "text": cleaned, "is_final": False}),
                    loop,
                )

        try:
            self._stream_session = await asyncio.to_thread(self._asr.start_stream, _on_partial)
            if self._stream_session is None:
                logger.warning("RTASR session start returned None")
            else:
                self._session_ready = True
                if self._pending_audio:
                    logger.info("Flushing %d buffered chunks to RTASR", len(self._pending_audio))
                    for chunk in self._pending_audio:
                        self._asr.stream_append(self._stream_session, chunk)
                    self._pending_audio.clear()
        except Exception as e:
            logger.warning("Failed to start RTASR session: %s", e)
            self._stream_session = None

    async def feed_audio(self, pcm_f32: np.ndarray):
        if self._session_ready and self._stream_session is not None:
            self._asr.stream_append(self._stream_session, pcm_f32)
        else:
            self._pending_audio.append(pcm_f32)
        self._speech_buf.append(pcm_f32)

    async def handle_audio_bytes(self, b: bytes):
        size = len(b)
        self._rx_frame_count += 1
        self._rx_bytes_total += size
        self._rx_last_frame_bytes = size

        if size < 2 or (size % 2) != 0:
            self._rx_bad_frame_count += 1
            return
        if size < self.min_frame_bytes or size > self.max_frame_bytes:
            self._rx_bad_frame_count += 1

        pcm = np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768.0
        await self.feed_audio(pcm)

        now = time.monotonic()
        if (now - self._last_audio_debug_ts) >= 1.0:
            self._last_audio_debug_ts = now
            mismatch_ratio = 0.0
            if self._rx_frame_count > 0:
                mismatch_ratio = float(self._rx_bad_frame_count) / float(self._rx_frame_count)
            await self.send({
                "type": "debug_audio_profile",
                "rx_frames": int(self._rx_frame_count),
                "rx_bad_frames": int(self._rx_bad_frame_count),
                "rx_last_frame_bytes": int(self._rx_last_frame_bytes),
                "expected_frame_bytes": int(self.frame_bytes),
                "mismatch_ratio": round(mismatch_ratio, 4),
                "recommended": self._server_audio_profile(),
            })

    async def commit_asr(self) -> str:
        text = ""
        if self._stream_session is not None:
            try:
                text = await asyncio.to_thread(self._asr.stream_commit, self._stream_session)
                text = self._asr_post(text, context=self._asr_context_text(), is_partial=False).strip()
            except Exception as e:
                logger.warning("RTASR commit failed: %s", e)
                text = ""
            finally:
                await self.close_stream_asr()

        if not text and self._speech_buf:
            audio = np.concatenate(self._speech_buf, axis=0)
            if len(audio) > 4800:
                try:
                    text = await asyncio.to_thread(self._asr.transcribe, audio)
                    text = self._asr_post(text, context=self._asr_context_text(), is_partial=False).strip()
                except Exception as e:
                    logger.warning("Whisper fallback failed: %s", e)

        self._speech_buf.clear()
        return text

    async def close_stream_asr(self):
        self._session_ready = False
        self._pending_audio.clear()
        if self._stream_session is None:
            return
        s = self._stream_session
        self._stream_session = None
        try:
            await asyncio.to_thread(self._asr.stream_close, s)
        except Exception:
            pass

    # ---- LLM + TTS ----
    async def run_pipeline(self, user_text: str):
        await self._cancel_llm()
        self._cancel.clear()

        self._history.append({"role": "user", "content": user_text})
        while len(self._history) > self._max_history_turns * 2:
            self._history.pop(0)

        async def _runner():
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are DeepCoke, a voice assistant for coking engineering, coal chemistry, and "
                        "blast-furnace related processes. Prefer coking-domain interpretation for ASR homophone "
                        "ambiguities (for example: '交换工艺/交化工艺/胶化工艺' usually means '焦化工艺'). "
                        "If ambiguity remains, ask one short clarification question first. "
                        "Answer concisely in natural spoken style and always use Simplified Chinese."
                    ),
                }
            ] + list(self._history)
            full_reply = ""
            buf = ""
            try:
                async for delta in deepseek_stream_chat(messages):
                    if self._cancel.is_set():
                        return
                    await self.send({"type": "llm_delta", "text": delta})
                    full_reply += delta
                    buf += delta
                    sents, buf = split_into_sentences(buf)
                    for s in sents:
                        if self._cancel.is_set():
                            return
                        sent = self._post(s.strip())
                        if sent:
                            self._sentence_id += 1
                            await self._tts_q.put((self._sentence_id, sent))

                tail = buf.strip()
                if tail and not self._cancel.is_set():
                    self._sentence_id += 1
                    await self._tts_q.put((self._sentence_id, self._post(tail)))

                await self.send({"type": "llm_done"})
                if full_reply:
                    self._history.append({"role": "assistant", "content": full_reply})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await self.send({"type": "error", "message": f"LLM error: {e}"})
                await self.send({"type": "state", "state": "idle"})

        self._llm_task = asyncio.create_task(_runner())

    async def tts_worker(self):
        """TTS worker with look-ahead: synthesize next sentence while current one plays."""
        prefetch: asyncio.Task | None = None
        prefetch_item: tuple[int, str] | None = None

        while not self._closed:
            # If we have a prefetched result, use it; otherwise wait for queue
            if prefetch is not None and prefetch_item is not None:
                sid, sent = prefetch_item
                try:
                    res = await prefetch
                except asyncio.CancelledError:
                    prefetch = None
                    prefetch_item = None
                    continue
                except Exception as e:
                    logger.warning("TTS prefetch exception: %s", e)
                    res = None
                prefetch = None
                prefetch_item = None
            else:
                sid, sent = await self._tts_q.get()
                if self._cancel.is_set():
                    continue
                await self.send({"type": "state", "state": "speaking"})
                try:
                    res = await asyncio.to_thread(self._tts.synth, sent)
                except Exception as e:
                    logger.warning("TTS synth exception: %s", e)
                    await self.send({"type": "error", "message": f"TTS error: {e}"})
                    await self.send({"type": "state", "state": "idle"})
                    continue

            if self._cancel.is_set():
                if prefetch and not prefetch.done():
                    prefetch.cancel()
                prefetch = None
                prefetch_item = None
                continue

            # Start prefetching next sentence while we send current one
            if not self._tts_q.empty():
                try:
                    next_item = self._tts_q.get_nowait()
                    next_sid, next_sent = next_item
                    prefetch_item = next_item
                    prefetch = asyncio.create_task(asyncio.to_thread(self._tts.synth, next_sent))
                except Exception:
                    pass

            await self.send({"type": "state", "state": "speaking"})
            if res is None:
                await self.send(
                    {
                        "type": "tts_audio",
                        "sentence_id": sid,
                        "audio_b64": "",
                        "mime": "audio/wav",
                        "text": sent,
                    }
                )
                continue
            await self.send(
                {
                    "type": "tts_audio",
                    "sentence_id": sid,
                    "audio_b64": b64encode_wav(res.wav_bytes),
                    "mime": res.mime,
                    "text": sent,
                }
            )

    async def interrupt(self):
        self._cancel.set()
        await self._cancel_llm()
        await self.close_stream_asr()
        self._speech_buf.clear()
        self._in_speech = False
        while not self._tts_q.empty():
            with contextlib.suppress(Exception):
                self._tts_q.get_nowait()
        self._cancel.clear()
        await self.send({"type": "state", "state": "idle"})

    async def _cancel_llm(self):
        if self._llm_task and not self._llm_task.done():
            self._llm_task.cancel()
            with contextlib.suppress(Exception):
                await self._llm_task
        self._llm_task = None

    async def close(self):
        self._closed = True
        self._cancel.set()
        await self._cancel_llm()
        await self.close_stream_asr()


@router.websocket("/ws/simple")
async def ws_simple(websocket: WebSocket):
    await websocket.accept()
    session = SimpleSession(websocket)
    await session.send({"type": "state", "state": "idle"})
    await session.send_audio_profile()

    tts_task = asyncio.create_task(session.tts_worker())

    try:
        while True:
            msg = await websocket.receive()

            if "bytes" in msg and msg["bytes"] is not None:
                b = msg["bytes"]
                if session._in_speech:
                    await session.handle_audio_bytes(b)
                continue

            if "text" in msg and msg["text"] is not None:
                try:
                    payload = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                t = payload.get("type")

                if t == "speech_start":
                    session._in_speech = True
                    session._speech_buf.clear()
                    session._profile_warn_sent = False
                    session._client_audio_profile = payload.get("audio_profile") or {}
                    await session.check_and_report_audio_profile()

                    if "pre_audio" in payload:
                        try:
                            pre_bytes = base64.b64decode(payload["pre_audio"])
                            if pre_bytes and (len(pre_bytes) % 2) == 0:
                                pre_pcm = np.frombuffer(pre_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                                session._pending_audio.append(pre_pcm)
                                session._speech_buf.append(pre_pcm)
                        except Exception:
                            pass

                    asyncio.create_task(session.start_stream_asr())
                    await session.send({"type": "state", "state": "listening"})
                    continue

                if t == "speech_end":
                    session._in_speech = False
                    await session.send({"type": "state", "state": "thinking"})
                    text = await session.commit_asr()
                    if text:
                        await session.send({"type": "asr", "text": text, "is_final": True})
                        await session.run_pipeline(text)
                    else:
                        await session.send({"type": "asr", "text": "", "is_final": True})
                        await session.send({"type": "state", "state": "idle"})
                    continue

                if t == "text":
                    raw = (payload.get("text") or "").strip()
                    if not raw:
                        continue
                    await session.interrupt()
                    await session.send({"type": "state", "state": "thinking"})
                    await session.run_pipeline(raw)
                    continue

                if t == "interrupt":
                    await session.interrupt()
                    continue

                if t == "profile":
                    await session.send_audio_profile()
                    continue

    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        tts_task.cancel()
        with contextlib.suppress(Exception):
            await tts_task
