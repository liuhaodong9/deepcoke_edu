from __future__ import annotations
import asyncio
import contextlib
import json
import logging
import time
from collections import deque

import httpx
import numpy as np
from fastapi import WebSocket

logger = logging.getLogger("voice-agent")

from app.core.config import settings
from app.services.asr_postprocess import ASRTextPostProcessor
from app.services.asr_service import WhisperASR
from app.services.deepseek_service import deepseek_stream_chat, split_into_sentences
from app.services.term_postprocess import TermPostProcessor
from app.services.tts_service import SparkTTSCLI, b64encode_wav
from app.services.vad_service import SileroVAD


class AgentSession:
    """One WebSocket connection = one agent session."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self.sample_rate = 16000
        self._audio_q: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=200)
        self._vad = SileroVAD(sample_rate=self.sample_rate, threshold=settings.VAD_THRESHOLD)
        self._asr = WhisperASR()

        glossary_dir = str((__import__("pathlib").Path(__file__).resolve().parents[3] / "glossary"))
        self._asr_post = ASRTextPostProcessor(glossary_dir=glossary_dir)
        self._post = TermPostProcessor(glossary_dir=glossary_dir)
        self._tts = SparkTTSCLI()

        # VAD state
        self._in_speech = False
        self._speech_buf: list[np.ndarray] = []
        self._silence_ms = 0
        self._speech_ms = 0

        # Concurrency control
        self._llm_task: asyncio.Task | None = None
        self._partial_task: asyncio.Task | None = None
        self._cancel_event = asyncio.Event()
        self._stream_session = None

        # Partial ASR control
        self._last_partial_emit_ms = 0.0
        self._last_partial_text = ""
        provider = getattr(self._asr, "provider", "whisper")
        local_partial_ok = bool(getattr(self._asr, "supports_local_partial", False))
        self._streaming_asr_capable = bool(getattr(self._asr, "supports_realtime_session", False))
        self._partial_enabled = settings.ASR_PARTIAL_ENABLED and (
            provider == "whisper" or local_partial_ok or settings.ASR_PARTIAL_ALLOW_REMOTE_PROVIDER
        )

        # Context for ASR reranking
        max_turns = max(1, int(settings.ASR_CONTEXT_WINDOW_TURNS))
        self._asr_history: deque[str] = deque(maxlen=max_turns)

        # TTS queue (sentence-level)
        self._tts_q: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        self._sentence_id = 0

        self._state = "idle"
        self._closed = False

        # Backend audio debug counters (for frontend visual diagnostics)
        self._frame_count = 0
        self._last_frame_size = 0
        self._last_frame_rms = 0.0
        self._last_audio_debug_ts = 0.0

    async def close(self):
        self._closed = True
        self._cancel_event.set()
        await self._cancel_llm()
        await self._cancel_partial_asr()
        await self._close_stream_asr()
        self._vad.reset()
        try:
            await self.ws.close()
        except Exception:
            pass

    async def send_json(self, obj: dict):
        if self._closed:
            return
        await self.ws.send_text(json.dumps(obj, ensure_ascii=False))

    async def send_error(self, msg: str):
        await self.send_json({"type": "error", "message": msg})

    async def send_state(self, state: str):
        if state == self._state:
            return
        self._state = state
        await self.send_json({"type": "state", "state": state})

    async def handle_control(self, payload: dict):
        t = payload.get("type")
        logger.info("control message: %s", t)
        if t == "start":
            await self._reset_buffers()
            await self._start_stream_asr()
            await self.send_state("listening")
        elif t == "stop":
            await self._finalize_segment(force=True)
            await self._close_stream_asr()
            await self.send_state("idle")
        elif t == "interrupt":
            await self._interrupt()
        elif t == "text":
            text = (payload.get("text") or "").strip()
            if not text:
                return
            await self._interrupt()
            await self.send_state("thinking")
            await self._run_llm_pipeline(user_text=text)
        else:
            await self.send_error(f"Unknown control type: {t}")

    async def handle_audio_bytes(self, b: bytes):
        self._last_frame_size = len(b)
        if len(b) != 512 * 2:
            logger.warning("audio frame wrong size: %d (expected %d)", len(b), 512 * 2)
            return

        pcm = np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        self._last_frame_rms = rms
        self._frame_count += 1

        if self._frame_count % 100 == 1:
            logger.info("audio frame #%d, rms=%.5f, queue=%d", self._frame_count, rms, self._audio_q.qsize())

        try:
            self._audio_q.put_nowait(pcm)
        except asyncio.QueueFull:
            logger.warning("audio queue full, dropping frame")

        now = time.monotonic()
        if (now - self._last_audio_debug_ts) >= 1.0:
            self._last_audio_debug_ts = now
            await self.send_json({
                "type": "debug_audio_rx",
                "frames": int(self._frame_count),
                "rms": round(float(self._last_frame_rms), 6),
                "queue": int(self._audio_q.qsize()),
                "last_frame_bytes": int(self._last_frame_size),
                "in_speech": bool(self._in_speech),
                "speech_ms": int(self._speech_ms),
            })

    async def _reset_buffers(self):
        self._in_speech = False
        self._speech_buf.clear()
        self._silence_ms = 0
        self._speech_ms = 0
        self._cancel_event.clear()
        self._last_partial_emit_ms = 0.0
        self._last_partial_text = ""
        self._vad.reset()
        await self._cancel_llm()
        await self._cancel_partial_asr()
        await self._close_stream_asr()

        while not self._audio_q.empty():
            with contextlib.suppress(Exception):
                self._audio_q.get_nowait()
        while not self._tts_q.empty():
            with contextlib.suppress(Exception):
                self._tts_q.get_nowait()
        self._sentence_id = 0

    async def _interrupt(self):
        self._cancel_event.set()
        await self._cancel_llm()
        await self._cancel_partial_asr()
        await self._close_stream_asr()
        while not self._tts_q.empty():
            with contextlib.suppress(Exception):
                self._tts_q.get_nowait()
        self._cancel_event.clear()
        self._last_partial_text = ""
        await self.send_state("listening")

    async def _cancel_llm(self):
        if self._llm_task and not self._llm_task.done():
            self._llm_task.cancel()
            with contextlib.suppress(Exception):
                await self._llm_task
        self._llm_task = None

    async def _cancel_partial_asr(self):
        if self._partial_task and not self._partial_task.done():
            self._partial_task.cancel()
            with contextlib.suppress(Exception):
                await self._partial_task
        self._partial_task = None

    async def _start_stream_asr(self):
        if (not self._streaming_asr_capable) or (self._stream_session is not None):
            return
        if self._loop is None:
            with contextlib.suppress(RuntimeError):
                self._loop = asyncio.get_running_loop()
        self._stream_session = await asyncio.to_thread(self._asr.start_stream, self._on_stream_partial_from_thread)

    async def _close_stream_asr(self):
        if self._stream_session is None:
            return
        s = self._stream_session
        self._stream_session = None
        await asyncio.to_thread(self._asr.stream_close, s)

    async def _commit_stream_asr(self) -> str:
        if self._stream_session is None:
            return ""
        s = self._stream_session
        text = ""
        try:
            text = await asyncio.to_thread(self._asr.stream_commit, s)
        finally:
            await self._close_stream_asr()
        return (text or "").strip()

    def _on_stream_partial_from_thread(self, text: str):
        if self._closed or self._cancel_event.is_set():
            return
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(lambda: asyncio.create_task(self._handle_stream_partial(text)))

    async def _handle_stream_partial(self, text: str):
        if self._closed or self._cancel_event.is_set() or (not self._in_speech):
            return
        cleaned = self._asr_post(text, context=self._asr_context_text(), is_partial=True).strip()
        if cleaned and cleaned != self._last_partial_text:
            self._last_partial_text = cleaned
            await self.send_json({"type": "asr_partial", "text": cleaned, "is_final": False})

    def _asr_context_text(self) -> str:
        if not self._asr_history:
            return ""
        return " ".join(self._asr_history)

    async def _run_asr(self, audio: np.ndarray, is_partial: bool) -> str:
        asr_func = self._asr.transcribe_partial if is_partial else self._asr.transcribe
        text = await asyncio.to_thread(asr_func, audio)
        text = self._asr_post(text, context=self._asr_context_text(), is_partial=is_partial)
        return (text or "").strip()

    async def _partial_asr_worker(self, audio: np.ndarray):
        try:
            if self._cancel_event.is_set() or self._closed:
                return
            text = await self._run_asr(audio=audio, is_partial=True)
            if self._cancel_event.is_set() or self._closed:
                return
            if text and text != self._last_partial_text:
                self._last_partial_text = text
                await self.send_json({"type": "asr_partial", "text": text, "is_final": False})
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    def _partial_window_audio(self) -> np.ndarray | None:
        if not self._speech_buf:
            return None
        audio = np.concatenate(self._speech_buf, axis=0)
        window_sec = max(1.0, float(settings.ASR_PARTIAL_WINDOW_SEC))
        window_samples = int(window_sec * self.sample_rate)
        if window_samples > 0 and len(audio) > window_samples:
            audio = audio[-window_samples:]
        return audio

    def _should_emit_partial(self) -> bool:
        if not self._partial_enabled:
            return False
        if self._stream_session is not None:
            return False
        if not self._in_speech:
            return False
        if self._partial_task and not self._partial_task.done():
            return False
        if self._speech_ms < max(0, int(settings.ASR_PARTIAL_MIN_AUDIO_MS)):
            return False
        now_ms = time.monotonic() * 1000.0
        interval_ms = max(120, int(settings.ASR_PARTIAL_INTERVAL_MS))
        if now_ms - self._last_partial_emit_ms < interval_ms:
            return False
        self._last_partial_emit_ms = now_ms
        return True

    async def vad_worker(self):
        """Consume audio chunks -> VAD -> form utterance -> ASR -> LLM pipeline."""
        frame_ms = int(512 / self.sample_rate * 1000)  # 32ms

        while not self._closed:
            chunk = await self._audio_q.get()
            ev = self._vad(chunk)

            if ev and ev.event == "speech_start":
                logger.info("VAD: speech_start at %.2fs", ev.time_s)
                await self.send_json({"type": "debug_vad", "event": "speech_start", "time_s": round(float(ev.time_s), 3)})
                self._in_speech = True
                self._speech_ms = 0
                self._silence_ms = 0
                self._speech_buf.clear()
                self._last_partial_text = ""
                self._last_partial_emit_ms = 0.0
                if self._streaming_asr_capable and self._stream_session is None:
                    await self._start_stream_asr()
                await self.send_state("listening")

            if self._in_speech:
                self._speech_buf.append(chunk)
                self._speech_ms += frame_ms
                if self._stream_session is not None:
                    self._asr.stream_append(self._stream_session, chunk)

                if ev and ev.event == "speech_end":
                    logger.info("VAD: speech_end at %.2fs, speech_ms=%d", ev.time_s, self._speech_ms)
                    await self.send_json({"type": "debug_vad", "event": "speech_end", "time_s": round(float(ev.time_s), 3), "speech_ms": int(self._speech_ms)})
                    await self._finalize_segment(force=False)
                    continue

                if self._should_emit_partial():
                    snapshot = self._partial_window_audio()
                    if snapshot is not None and len(snapshot) > 0:
                        self._partial_task = asyncio.create_task(self._partial_asr_worker(snapshot))

    async def _finalize_segment(self, force: bool):
        if not self._speech_buf:
            return

        if (not force) and self._speech_ms < settings.VAD_MIN_SPEECH_MS:
            await self.send_json({
                "type": "debug_vad",
                "event": "segment_discarded_too_short",
                "speech_ms": int(self._speech_ms),
                "min_speech_ms": int(settings.VAD_MIN_SPEECH_MS),
            })
            self._speech_buf.clear()
            self._in_speech = False
            await self._close_stream_asr()
            return

        audio = np.concatenate(self._speech_buf, axis=0)
        self._speech_buf.clear()
        self._in_speech = False
        await self._cancel_partial_asr()
        await self.send_state("thinking")

        text = ""
        if self._stream_session is not None:
            text = await self._commit_stream_asr()
            text = self._asr_post(text, context=self._asr_context_text(), is_partial=False).strip()
        if not text:
            text = await self._run_asr(audio=audio, is_partial=False)
        if not text:
            await self.send_state("listening")
            return

        self._last_partial_text = text
        self._asr_history.append(text)
        await self.send_json({"type": "asr", "text": text, "is_final": True})
        await self._run_llm_pipeline(user_text=text)

    async def _run_llm_pipeline(self, user_text: str):
        await self._cancel_llm()
        self._cancel_event.clear()

        async def _runner():
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful voice assistant. Answer concisely in a natural spoken style. "
                        "When speaking Chinese, always use Simplified Chinese characters."
                    ),
                },
                {"role": "user", "content": user_text},
            ]

            buf = ""
            try:
                async for delta in deepseek_stream_chat(messages):
                    if self._cancel_event.is_set():
                        return
                    await self.send_json({"type": "llm_delta", "text": delta})
                    buf += delta
                    sents, buf = split_into_sentences(buf)
                    for s in sents:
                        if self._cancel_event.is_set():
                            return
                        sent = self._post(s.strip())
                        if sent:
                            self._sentence_id += 1
                            await self._tts_q.put((self._sentence_id, sent))

                tail = buf.strip()
                if tail and not self._cancel_event.is_set():
                    self._sentence_id += 1
                    await self._tts_q.put((self._sentence_id, self._post(tail)))

                await self.send_json({"type": "llm_done"})
            except asyncio.CancelledError:
                raise
            except httpx.HTTPStatusError as e:
                status = getattr(e.response, "status_code", None)
                if status == 401:
                    await self.send_error(
                        "DeepSeek auth failed (401). Check DEEPSEEK_API_KEY in backend/.env and restart backend."
                    )
                else:
                    await self.send_error(f"DeepSeek API error: HTTP {status}")
                await self.send_state("listening")
            except Exception as e:
                await self.send_error(f"LLM pipeline failed: {e}")
                await self.send_state("listening")

        self._llm_task = asyncio.create_task(_runner())

    async def tts_worker(self):
        """Consume sentence queue -> Spark-TTS -> send wav base64 to frontend."""
        while not self._closed:
            sid, sent = await self._tts_q.get()
            if self._cancel_event.is_set():
                continue

            await self.send_state("speaking")

            res = self._tts.synth(sent)
            if res is None:
                await self.send_json({
                    "type": "tts_audio",
                    "sentence_id": sid,
                    "audio_b64": "",
                    "mime": "audio/wav",
                    "text": sent,
                })
                continue

            await self.send_json({
                "type": "tts_audio",
                "sentence_id": sid,
                "audio_b64": b64encode_wav(res.wav_bytes),
                "mime": res.mime,
                "text": sent,
            })
