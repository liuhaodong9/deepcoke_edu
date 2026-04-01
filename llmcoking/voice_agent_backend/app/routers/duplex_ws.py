"""
Full-duplex voice WebSocket: continuous audio stream with server-side VAD.

Key improvements over simple_ws:
1. Server-side Silero VAD (no client speech_start/speech_end needed)
2. ASR partial stabilisation triggers LLM pre-inference (~500ms early)
3. TTS parallel pre-synthesis (next sentence synthesised while current plays)
4. Instant barge-in: VAD detects speech during AI output -> immediate interrupt
"""

from __future__ import annotations

import asyncio
import base64
import collections
import contextlib
import json
import logging
import time

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.services.asr_postprocess import ASRTextPostProcessor
from app.services.asr_service import WhisperASR
from app.services.deepseek_service import deepseek_stream_chat
from app.services.term_postprocess import TermPostProcessor
from app.services.tts_service import SparkTTSCLI, b64encode_wav
from app.services.vad_service import SileroVAD

logger = logging.getLogger("duplex-voice")
router = APIRouter()

# ---------------------------------------------------------------------------
# Sentence splitting – finer granularity for faster TTS turnaround
# ---------------------------------------------------------------------------
import re

# Split on Chinese/English sentence-ending punctuation AND on commas / semicolons
# so TTS can start speaking sooner.
_CLAUSE_SPLIT_RE = re.compile(r'(?<=[。！？.!?；;，,])')

def split_into_clauses(buf: str, min_len: int = 6) -> tuple[list[str], str]:
    """Split buffer into speakable clauses.

    Returns (complete_clauses, remaining_buffer).
    Clauses shorter than *min_len* are merged with the next one to avoid
    choppy TTS output.
    """
    parts = _CLAUSE_SPLIT_RE.split(buf)
    if len(parts) <= 1:
        return [], buf

    clauses: list[str] = []
    accum = ""
    # All parts except the last are complete (followed by punctuation).
    for p in parts[:-1]:
        accum += p
        if len(accum) >= min_len:
            clauses.append(accum)
            accum = ""
    # Last part is the incomplete remainder.
    remainder = accum + parts[-1]
    return clauses, remainder


# ---------------------------------------------------------------------------
# Duplex session
# ---------------------------------------------------------------------------

# Server-side VAD parameters
_VAD_WINDOW = 512  # Silero requires exactly 512 samples (32 ms @ 16 kHz)
_PRE_BUF_FRAMES = 15  # ~480 ms of pre-speech audio to feed ASR

# ASR partial stabilisation: if the partial text doesn't change for this long,
# we pre-trigger LLM inference before the user finishes speaking.
_PARTIAL_STABLE_SEC = 0.55


class DuplexSession:
    """Full-duplex voice session with server-side VAD."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self._loop = asyncio.get_running_loop()
        self._closed = False
        self._cancel = asyncio.Event()

        # Services
        self._asr = WhisperASR()
        glossary_dir = str((__import__("pathlib").Path(__file__).resolve().parents[3] / "glossary"))
        self._asr_post = ASRTextPostProcessor(glossary_dir=glossary_dir)
        self._post = TermPostProcessor(glossary_dir=glossary_dir)
        self._tts = SparkTTSCLI()
        self._vad = SileroVAD(
            sample_rate=16000,
            threshold=float(getattr(settings, "VAD_THRESHOLD", 0.5)),
        )

        # Audio profile
        self.sample_rate_hz = 16000
        self.bits_per_sample = 16

        # VAD state
        self._user_speaking = False
        self._ai_speaking = False
        self._pre_buf: collections.deque[np.ndarray] = collections.deque(maxlen=_PRE_BUF_FRAMES)
        self._vad_buf = np.zeros(0, dtype=np.float32)

        # ASR state
        self._stream_session = None
        self._session_ready = False
        self._pending_audio: list[np.ndarray] = []
        self._speech_buf: list[np.ndarray] = []
        self._domain_hint = "焦化 炼焦 焦炭 煤焦油 配煤 高炉 焦炉 干熄焦 煤化工"

        # ASR partial monitoring (for early LLM trigger)
        self._current_partial = ""
        self._last_stable_partial = ""
        self._partial_stable_since = 0.0
        self._pre_triggered = False
        self._pre_trigger_text = ""

        # LLM
        self._llm_task: asyncio.Task | None = None
        self._llm_done = True  # True when LLM stream is finished or idle
        self._history: list[dict] = []
        self._max_history_turns = 20

        # TTS
        self._tts_q: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue()
        self._sentence_id = 0

        # Audio input queue (from WebSocket reader to audio processor)
        self._audio_q: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=500)

    # ---- Helpers ----

    async def send(self, obj: dict):
        if self._closed:
            return
        try:
            await self.ws.send_text(json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass

    def _asr_context_text(self) -> str:
        parts: list[str] = [self._domain_hint]
        for item in self._history[-8:]:
            if isinstance(item, dict):
                txt = str(item.get("content") or "").strip()
                if txt:
                    parts.append(txt[:200])
        return " ".join(parts)

    # ---- Server-side VAD + Audio Processing ----

    async def audio_processor(self):
        """Main loop: pull audio from queue -> VAD -> ASR routing."""
        while not self._closed:
            try:
                pcm = await asyncio.wait_for(self._audio_q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            # Accumulate for VAD (needs exactly 512 samples)
            self._vad_buf = np.concatenate([self._vad_buf, pcm])

            while len(self._vad_buf) >= _VAD_WINDOW:
                chunk = self._vad_buf[:_VAD_WINDOW]
                self._vad_buf = self._vad_buf[_VAD_WINDOW:]

                event = self._vad(chunk)

                if event is not None:
                    if event.event == "speech_start":
                        await self._on_vad_speech_start()
                    elif event.event == "speech_end":
                        await self._on_vad_speech_end()

                # Feed audio to ASR or pre-buffer
                if self._user_speaking:
                    await self._feed_asr(chunk)
                else:
                    self._pre_buf.append(chunk)

    async def _on_vad_speech_start(self):
        """Server detected user started speaking."""
        # Barge-in: if AI is speaking, interrupt immediately
        if self._ai_speaking or (self._llm_task and not self._llm_task.done()):
            await self._interrupt()

        self._user_speaking = True
        self._pre_triggered = False
        self._pre_trigger_text = ""
        self._current_partial = ""
        self._last_stable_partial = ""
        self._partial_stable_since = time.monotonic()

        await self.send({"type": "state", "state": "listening"})

        # Close old ASR session in background (don't block on it)
        if self._stream_session is not None:
            old = self._stream_session
            self._stream_session = None
            self._session_ready = False
            self._pending_audio.clear()
            asyncio.create_task(asyncio.to_thread(self._asr.stream_close, old))

        # Start new streaming ASR session
        await self._start_stream_asr()

        # Feed pre-buffered audio (captures the beginning of speech)
        for chunk in self._pre_buf:
            await self._feed_asr(chunk)
        self._pre_buf.clear()

    async def _on_vad_speech_end(self):
        """Server detected user stopped speaking."""
        if not self._user_speaking:
            return
        self._user_speaking = False

        await self.send({"type": "state", "state": "thinking"})

        # Get final ASR text
        final_text = await self._commit_asr()

        if not final_text:
            await self.send({"type": "asr", "text": "", "is_final": True})
            await self.send({"type": "state", "state": "idle"})
            return

        await self.send({"type": "asr", "text": final_text, "is_final": True})

        # Check if LLM was already pre-triggered with matching text
        if self._pre_triggered and self._pre_trigger_text.strip() == final_text.strip():
            # LLM is already running with the right text – let it continue
            logger.info("LLM pre-triggered text matches final ASR, continuing")
        else:
            # Cancel any pre-triggered LLM and start fresh
            if self._pre_triggered:
                logger.info("Pre-triggered text mismatch, restarting LLM")
            await self._cancel_llm()
            await self._run_pipeline(final_text)

    # ---- ASR Partial Monitoring (Early LLM Trigger) ----

    async def partial_monitor(self):
        """Background task: monitor ASR partial text stability.

        When the partial text hasn't changed for ~500ms, pre-trigger LLM
        so the response starts generating before the user finishes speaking.
        """
        while not self._closed:
            await asyncio.sleep(0.1)

            if not self._user_speaking or not self._current_partial:
                continue

            now = time.monotonic()
            partial = self._current_partial.strip()

            if partial and partial == self._last_stable_partial:
                elapsed = now - self._partial_stable_since
                if elapsed >= _PARTIAL_STABLE_SEC and not self._pre_triggered and len(partial) >= 2:
                    # Partial has been stable long enough – pre-trigger LLM
                    self._pre_triggered = True
                    self._pre_trigger_text = partial
                    logger.info("Pre-triggering LLM with stable partial: %s", partial[:50])
                    await self.send({"type": "state", "state": "thinking"})
                    await self._run_pipeline(partial)
            else:
                # Partial changed – reset stability timer
                self._last_stable_partial = partial
                self._partial_stable_since = now
                # If LLM was pre-triggered with old text, cancel it
                if self._pre_triggered:
                    logger.info("Partial changed, cancelling pre-triggered LLM")
                    await self._cancel_llm()
                    self._pre_triggered = False
                    self._pre_trigger_text = ""

    # ---- Streaming ASR ----

    async def _start_stream_asr(self):
        if self._stream_session is not None or self._session_ready:
            return
        if not (self._asr.doubao_rt and self._asr.doubao_rt.enabled):
            return

        self._pending_audio.clear()
        self._speech_buf.clear()
        loop = self._loop

        def _on_partial(text: str):
            if self._closed or self._cancel.is_set():
                return
            cleaned = self._asr_post(text, context=self._asr_context_text(), is_partial=True).strip()
            if cleaned:
                self._current_partial = cleaned
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
                    for chunk in self._pending_audio:
                        self._asr.stream_append(self._stream_session, chunk)
                    self._pending_audio.clear()
        except Exception as e:
            logger.warning("Failed to start RTASR session: %s", e)
            self._stream_session = None

    async def _feed_asr(self, pcm_f32: np.ndarray):
        if self._session_ready and self._stream_session is not None:
            self._asr.stream_append(self._stream_session, pcm_f32)
        else:
            self._pending_audio.append(pcm_f32)
        self._speech_buf.append(pcm_f32)

    async def _commit_asr(self) -> str:
        text = ""
        if self._stream_session is not None:
            try:
                text = await asyncio.to_thread(self._asr.stream_commit, self._stream_session)
                text = self._asr_post(text, context=self._asr_context_text(), is_partial=False).strip()
            except Exception as e:
                logger.warning("RTASR commit failed: %s", e)
                text = ""
            finally:
                await self._close_stream_asr()

        # Fallback to batch whisper
        if not text and self._speech_buf:
            audio = np.concatenate(self._speech_buf, axis=0)
            if len(audio) > 4800:
                try:
                    text = await asyncio.to_thread(self._asr.transcribe, audio)
                    text = self._asr_post(text, context=self._asr_context_text(), is_partial=False).strip()
                except Exception as e:
                    logger.warning("Whisper fallback failed: %s", e)

        self._speech_buf.clear()
        self._current_partial = ""
        return text

    async def _close_stream_asr(self):
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

    # ---- LLM + TTS Pipeline ----

    async def _run_pipeline(self, user_text: str):
        await self._cancel_llm()
        self._cancel.clear()
        self._llm_done = False

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

                    # Use finer clause-level splitting for faster TTS
                    clauses, buf = split_into_clauses(buf)
                    for clause in clauses:
                        if self._cancel.is_set():
                            return
                        processed = self._post(clause.strip())
                        if processed:
                            self._sentence_id += 1
                            await self._tts_q.put((self._sentence_id, processed))

                # Flush remaining buffer
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
            finally:
                self._llm_done = True
                # Sentinel: tell TTS worker that no more sentences are coming
                with contextlib.suppress(Exception):
                    await self._tts_q.put(None)

        self._llm_task = asyncio.create_task(_runner())

    async def tts_worker(self):
        """TTS worker with look-ahead parallel synthesis."""
        prefetch: asyncio.Task | None = None
        prefetch_item: tuple[int, str] | None = None

        while not self._closed:
            # Use prefetched result if available
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
                item = await self._tts_q.get()
                # Sentinel: LLM finished, no more sentences
                if item is None:
                    if self._tts_q.empty() and prefetch is None:
                        self._ai_speaking = False
                        await self.send({"type": "state", "state": "idle"})
                    continue
                sid, sent = item
                if self._cancel.is_set():
                    continue
                try:
                    res = await asyncio.to_thread(self._tts.synth, sent)
                except Exception as e:
                    logger.warning("TTS synth exception: %s", e)
                    await self.send({"type": "error", "message": f"TTS error: {e}"})
                    continue

            if self._cancel.is_set():
                if prefetch and not prefetch.done():
                    prefetch.cancel()
                prefetch = None
                prefetch_item = None
                continue

            # Start prefetching next sentence while we send current
            if not self._tts_q.empty():
                try:
                    next_item = self._tts_q.get_nowait()
                    if next_item is not None:
                        prefetch_item = next_item
                        prefetch = asyncio.create_task(
                            asyncio.to_thread(self._tts.synth, next_item[1])
                        )
                except Exception:
                    pass

            self._ai_speaking = True
            await self.send({"type": "state", "state": "speaking"})

            if res is None:
                await self.send({
                    "type": "tts_audio",
                    "sentence_id": sid,
                    "audio_b64": "",
                    "mime": "audio/wav",
                    "text": sent,
                })
            else:
                await self.send({
                    "type": "tts_audio",
                    "sentence_id": sid,
                    "audio_b64": b64encode_wav(res.wav_bytes),
                    "mime": res.mime,
                    "text": sent,
                })

            # Only set idle when queue is empty, no prefetch pending, AND LLM is done
            if self._tts_q.empty() and (prefetch is None or prefetch_item is None) and self._llm_done:
                self._ai_speaking = False
                await self.send({"type": "state", "state": "idle"})

    # ---- Interruption ----

    async def _interrupt(self):
        """Immediately stop all AI output.

        IMPORTANT: Does NOT reset VAD or close ASR — the caller
        (_on_vad_speech_start) handles ASR teardown itself so
        barge-in speech detection keeps working.
        """
        self._cancel.set()
        self._ai_speaking = False
        self._llm_done = True
        await self._cancel_llm()
        # Drain TTS queue
        while not self._tts_q.empty():
            with contextlib.suppress(Exception):
                self._tts_q.get_nowait()
        self._cancel.clear()
        # Do NOT reset VAD here — user may still be speaking (barge-in)
        # Do NOT close ASR here — _on_vad_speech_start handles it
        await self.send({"type": "interrupt"})
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
        await self._close_stream_asr()


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/duplex")
async def ws_duplex(websocket: WebSocket):
    await websocket.accept()
    session = DuplexSession(websocket)
    await session.send({"type": "state", "state": "idle"})
    await session.send({
        "type": "audio_profile",
        "encoding": "pcm_s16le",
        "sample_rate_hz": 16000,
        "channels": 1,
        "bits_per_sample": 16,
        "mode": "full_duplex",
        "info": "Send continuous PCM audio as binary frames. Server handles VAD.",
    })

    # Start background workers
    processor_task = asyncio.create_task(session.audio_processor())
    tts_task = asyncio.create_task(session.tts_worker())
    partial_task = asyncio.create_task(session.partial_monitor())

    try:
        while True:
            msg = await websocket.receive()

            # Binary: raw PCM audio – always accepted (full-duplex)
            if "bytes" in msg and msg["bytes"] is not None:
                b = msg["bytes"]
                if len(b) >= 2 and (len(b) % 2) == 0:
                    pcm = np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768.0
                    try:
                        session._audio_q.put_nowait(pcm)
                    except asyncio.QueueFull:
                        # Drop oldest frame to keep real-time
                        try:
                            session._audio_q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        with contextlib.suppress(asyncio.QueueFull):
                            session._audio_q.put_nowait(pcm)
                continue

            # Text: JSON control messages
            if "text" in msg and msg["text"] is not None:
                try:
                    payload = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                t = payload.get("type")

                if t == "interrupt":
                    await session._interrupt()
                    continue

                if t == "text":
                    # Manual text input
                    raw = (payload.get("text") or "").strip()
                    if raw:
                        await session._interrupt()
                        await session.send({"type": "state", "state": "thinking"})
                        await session._run_pipeline(raw)
                    continue

                if t == "profile":
                    await session.send({
                        "type": "audio_profile",
                        "encoding": "pcm_s16le",
                        "sample_rate_hz": 16000,
                        "channels": 1,
                        "bits_per_sample": 16,
                        "mode": "full_duplex",
                    })
                    continue

    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        for task in [processor_task, tts_task, partial_task]:
            task.cancel()
            with contextlib.suppress(Exception):
                await task
