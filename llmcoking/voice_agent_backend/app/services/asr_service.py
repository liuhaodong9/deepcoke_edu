from __future__ import annotations
import base64
import contextlib
import hashlib
import hmac
import io
import json
import queue
import threading
import time
import uuid
import wave
from typing import Callable
from urllib.parse import quote, urlencode
import httpx
from websockets.sync.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed
import numpy as np
from app.core.config import settings


class LocalWhisperEngine:
    def __init__(self):
        self.model = None
        self.enabled = False
        self._load()

    def _load(self):
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception:
            self.enabled = False
            return

        device = settings.WHISPER_DEVICE
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"

        compute_type = settings.WHISPER_COMPUTE_TYPE
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        self.model = WhisperModel(settings.WHISPER_MODEL_SIZE, device=device, compute_type=compute_type)
        self.enabled = True

    def transcribe(self, audio_f32_16k: np.ndarray, language: str | None = None) -> str:
        if (not self.enabled) or (self.model is None):
            return ""
        audio = audio_f32_16k.astype(np.float32).reshape(-1)
        lang = language if language is not None else settings.WHISPER_LANGUAGE
        if isinstance(lang, str):
            lang = lang.strip().lower()
            if (not lang) or (lang == "auto"):
                lang = None
        segments, _ = self.model.transcribe(audio=audio, language=lang, task="transcribe")
        return "".join([seg.text for seg in segments]).strip()


class XfyunRTASREngine:
    def __init__(self):
        self.app_id = (settings.XFYUN_APP_ID or "").strip()
        self.api_key = (settings.XFYUN_API_KEY or "").strip()
        self.url = (settings.XFYUN_RTASR_URL or "wss://rtasr.xfyun.cn/v1/ws").strip()
        self.lang = (settings.XFYUN_RTASR_LANG or "cn").strip()
        self.chunk_ms = max(10, int(settings.XFYUN_RTASR_CHUNK_MS or 40))
        self.recv_timeout_sec = max(1.0, float(settings.XFYUN_RTASR_RECV_TIMEOUT_SEC or 5))
        self.enabled = bool(self.app_id and self.api_key)

    def _build_signed_url(self) -> str:
        ts = str(int(time.time()))
        base = f"{self.app_id}{ts}"
        md5_hex = hashlib.md5(base.encode("utf-8")).hexdigest()
        signa = base64.b64encode(
            hmac.new(self.api_key.encode("utf-8"), md5_hex.encode("utf-8"), digestmod=hashlib.sha1).digest()
        ).decode("utf-8")
        params = {"appid": self.app_id, "ts": ts, "signa": signa}
        if self.lang:
            params["lang"] = self.lang
        return f"{self.url}?{urlencode(params)}"

    @staticmethod
    def _to_pcm16(audio_f32_16k: np.ndarray) -> bytes:
        audio = np.asarray(audio_f32_16k, dtype=np.float32).reshape(-1)
        return np.clip(audio * 32768.0, -32768, 32767).astype("<i2").tobytes()

    @staticmethod
    def _iter_chunks(buf: bytes, size: int):
        for i in range(0, len(buf), size):
            yield buf[i:i + size]

    @staticmethod
    def _extract_text(data_obj: dict) -> str:
        # Most RTASR responses place text in cn.st.rt[].ws[].cw[].w
        parts: list[str] = []
        cn = data_obj.get("cn", {})
        st = cn.get("st", {}) if isinstance(cn, dict) else {}
        rt_list = st.get("rt", []) if isinstance(st, dict) else []
        if isinstance(rt_list, list):
            for rt in rt_list:
                if not isinstance(rt, dict):
                    continue
                ws_list = rt.get("ws", [])
                if not isinstance(ws_list, list):
                    continue
                for ws in ws_list:
                    if not isinstance(ws, dict):
                        continue
                    cw_list = ws.get("cw", [])
                    if isinstance(cw_list, list) and cw_list:
                        first = cw_list[0]
                        if isinstance(first, dict):
                            w = first.get("w", "")
                            if isinstance(w, str):
                                parts.append(w)

        if parts:
            return "".join(parts).strip()

        # Some results may put text in src
        src = data_obj.get("src")
        if isinstance(src, str):
            return src.strip()
        return ""

    def transcribe(self, audio_f32_16k: np.ndarray) -> str:
        if not self.enabled:
            return ""

        signed_url = self._build_signed_url()
        pcm_bytes = self._to_pcm16(audio_f32_16k)
        chunk_size = int(16000 * 2 * self.chunk_ms / 1000)
        chunk_size = max(320, chunk_size)

        seg_texts: dict[str, str] = {}
        with ws_connect(
            signed_url,
            open_timeout=10,
            close_timeout=3,
            max_size=2 * 1024 * 1024,
            ping_interval=None,
        ) as ws:
            # Startup message, e.g. {"action":"started","code":"0","sid":"..."}
            try:
                startup = ws.recv(timeout=5)
                if isinstance(startup, bytes):
                    startup = startup.decode("utf-8", errors="ignore")
                startup_obj = json.loads(startup)
                if startup_obj.get("action") == "error":
                    code = startup_obj.get("code")
                    desc = startup_obj.get("desc") or startup_obj.get("message", "")
                    raise RuntimeError(f"XFYUN RTASR error {code}: {desc}")
            except TimeoutError:
                pass

            for chunk in self._iter_chunks(pcm_bytes, chunk_size):
                ws.send(chunk)
                time.sleep(self.chunk_ms / 1000.0)

            ws.send('{"end": true}')

            idle_deadline = time.time() + self.recv_timeout_sec
            while True:
                remain = idle_deadline - time.time()
                if remain <= 0:
                    break
                try:
                    msg = ws.recv(timeout=remain)
                except TimeoutError:
                    break
                except ConnectionClosed:
                    break

                if isinstance(msg, bytes):
                    msg = msg.decode("utf-8", errors="ignore")
                try:
                    obj = json.loads(msg)
                except Exception:
                    continue

                if obj.get("action") == "error":
                    code = obj.get("code")
                    desc = obj.get("desc") or obj.get("message", "")
                    raise RuntimeError(f"XFYUN RTASR error {code}: {desc}")
                if obj.get("action") != "result":
                    continue
                if str(obj.get("code", "0")) != "0":
                    continue

                data_raw = obj.get("data")
                if not data_raw:
                    continue
                try:
                    data_obj = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
                except Exception:
                    continue
                if not isinstance(data_obj, dict):
                    continue

                seg_id = data_obj.get("seg_id", len(seg_texts))
                text_piece = self._extract_text(data_obj)
                if text_piece:
                    seg_texts[str(seg_id)] = text_piece
                idle_deadline = time.time() + self.recv_timeout_sec

        if not seg_texts:
            return ""
        ordered = [seg_texts[k] for k in sorted(seg_texts.keys(), key=lambda x: int(x) if str(x).isdigit() else 10**9)]
        return "".join(ordered).strip()


class DoubaoFlashASREngine:
    def __init__(self):
        self.endpoint = (
            settings.DOUBAO_ASR_ENDPOINT
            or "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
        ).strip()
        self.app_key = (settings.DOUBAO_API_APP_KEY or "").strip()
        self.access_key = (settings.DOUBAO_API_ACCESS_KEY or "").strip()
        self.resource_id = (settings.DOUBAO_API_RESOURCE_ID or "volc.bigasr.auc_turbo").strip()
        self.model_name = (settings.DOUBAO_ASR_MODEL_NAME or "bigmodel").strip()
        self.uid = (settings.DOUBAO_ASR_UID or "voice-agent").strip()
        self.timeout_sec = max(5.0, float(settings.DOUBAO_ASR_TIMEOUT_SEC or 30))
        self.enable_punc = bool(settings.DOUBAO_ASR_ENABLE_PUNC)
        self.enable_itn = bool(settings.DOUBAO_ASR_ENABLE_ITN)
        self.enabled = bool(self.app_key and self.access_key and self.resource_id and self.endpoint)

    @staticmethod
    def _to_wav_bytes(audio_f32_16k: np.ndarray, sample_rate: int = 16000) -> bytes:
        audio = np.asarray(audio_f32_16k, dtype=np.float32).reshape(-1)
        pcm16 = np.clip(audio * 32768.0, -32768, 32767).astype("<i2").tobytes()

        with io.BytesIO() as bio:
            with wave.open(bio, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm16)
            return bio.getvalue()

    @staticmethod
    def _extract_text(payload: object) -> str:
        texts: list[str] = []
        seen: set[str] = set()

        def add_text(val: object):
            if not isinstance(val, str):
                return
            s = val.strip()
            if (not s) or (s in seen):
                return
            seen.add(s)
            texts.append(s)

        def walk(node: object):
            if isinstance(node, dict):
                for k, v in node.items():
                    lk = str(k).lower()
                    if lk in {"text", "transcript", "sentence", "utterance", "src"}:
                        add_text(v)
                    elif lk in {
                        "result",
                        "results",
                        "data",
                        "payload",
                        "segments",
                        "utterances",
                        "items",
                        "nbest",
                        "alternatives",
                    }:
                        walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return "".join(texts).strip()

    def transcribe(self, audio_f32_16k: np.ndarray) -> str:
        if not self.enabled:
            return ""

        wav_bytes = self._to_wav_bytes(audio_f32_16k, sample_rate=16000)
        req_json = {
            "user": {"uid": self.uid or "voice-agent"},
            "audio": {"data": base64.b64encode(wav_bytes).decode("utf-8")},
            "request": {
                "model_name": self.model_name or "bigmodel",
                "enable_punc": self.enable_punc,
                "enable_itn": self.enable_itn,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

        with httpx.Client(timeout=self.timeout_sec) as client:
            resp = client.post(self.endpoint, json=req_json, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, dict):
            code = data.get("code")
            if code not in {None, 0, "0", 200, "200"}:
                msg = data.get("message") or data.get("msg") or data.get("error") or ""
                raise RuntimeError(f"Doubao ASR error {code}: {msg}")
            text = self._extract_text(data)
            if text:
                return text
        return ""


class DoubaoRealtimeASRSession:
    def __init__(
        self,
        url: str,
        model: str,
        api_key: str,
        resource_id: str,
        uid: str,
        open_timeout_sec: float,
        commit_timeout_sec: float,
        recv_timeout_sec: float,
        enable_punc: bool,
        enable_itn: bool,
        on_partial: Callable[[str], None] | None = None,
    ):
        self.url = (url or "").strip()
        self.model = (model or "bigmodel").strip()
        self.api_key = (api_key or "").strip()
        self.resource_id = (resource_id or "volc.bigasr.sauc.duration").strip()
        self.uid = (uid or "voice-agent").strip()
        self.open_timeout_sec = max(2.0, float(open_timeout_sec or 10))
        self.commit_timeout_sec = max(1.0, float(commit_timeout_sec or 10))
        self.recv_timeout_sec = max(1.0, float(recv_timeout_sec or 8))
        self.enable_punc = bool(enable_punc)
        self.enable_itn = bool(enable_itn)
        self.on_partial = on_partial

        self._audio_q: queue.Queue[bytes] = queue.Queue(maxsize=512)
        self._stop_evt = threading.Event()
        self._ready_evt = threading.Event()
        self._closed_evt = threading.Event()
        self._final_evt = threading.Event()
        self._commit_evt = threading.Event()
        self._thread: threading.Thread | None = None

        self._lock = threading.Lock()
        self._partial_text = ""
        self._final_text = ""
        self._error = ""

    @property
    def ready(self) -> bool:
        return self._ready_evt.is_set() and (not self._closed_evt.is_set()) and (not self._error)

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    @staticmethod
    def _to_pcm16(audio_f32_16k: np.ndarray) -> bytes:
        audio = np.asarray(audio_f32_16k, dtype=np.float32).reshape(-1)
        return np.clip(audio * 32768.0, -32768, 32767).astype("<i2").tobytes()

    def _set_error(self, msg: str):
        with self._lock:
            self._error = (msg or "unknown error").strip()

    def _set_partial(self, text: str):
        val = (text or "").strip()
        if not val:
            return
        do_emit = False
        with self._lock:
            if val != self._partial_text:
                self._partial_text = val
                do_emit = True
        if do_emit and self.on_partial:
            try:
                self.on_partial(val)
            except Exception:
                pass

    def _set_final(self, text: str):
        val = (text or "").strip()
        if not val:
            return
        with self._lock:
            self._final_text = val
            self._partial_text = val
        self._final_evt.set()

    def _build_url(self) -> str:
        if not self.url:
            return ""
        if "model=" in self.url:
            return self.url
        sep = "&" if "?" in self.url else "?"
        return f"{self.url}{sep}model={quote(self.model, safe='')}"

    def _handle_message(self, obj: dict):
        t = str(obj.get("type") or "").strip()
        if t == "error":
            err = obj.get("error", {})
            if isinstance(err, dict):
                code = err.get("code") or err.get("type") or ""
                msg = err.get("message") or ""
                self._set_error(f"{code} {msg}".strip())
            else:
                self._set_error(str(err))
            self._final_evt.set()
            return

        if t == "conversation.item.input_audio_transcription.result":
            self._set_partial(obj.get("transcript", ""))
            return

        if t == "conversation.item.input_audio_transcription.completed":
            text = obj.get("transcript", "")
            if not text:
                item = obj.get("item", {})
                if isinstance(item, dict):
                    text = item.get("transcript", "")
            self._set_final(text)
            return

    def _ws_send_json(self, ws, payload: dict):
        ws.send(json.dumps(payload, ensure_ascii=False))

    def _run(self):
        url = self._build_url()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.resource_id:
            headers["X-Api-Resource-Id"] = self.resource_id

        try:
            with ws_connect(
                url,
                additional_headers=headers,
                open_timeout=self.open_timeout_sec,
                close_timeout=2,
                max_size=8 * 1024 * 1024,
                ping_interval=None,
            ) as ws:
                self._ws_send_json(
                    ws,
                    {
                        "type": "transcription_session.update",
                        "input_audio_format": "pcm16",
                        "input_audio_transcription": {
                            "enabled": True,
                            "model": self.model,
                            "enable_punc": self.enable_punc,
                            "enable_itn": self.enable_itn,
                        },
                        "user": {"uid": self.uid},
                    },
                )
                self._ready_evt.set()

                idle_deadline = time.time() + self.recv_timeout_sec
                while not self._stop_evt.is_set():
                    # Drain audio queue and stream chunks.
                    while True:
                        try:
                            buf = self._audio_q.get_nowait()
                        except queue.Empty:
                            break
                        self._ws_send_json(
                            ws,
                            {"type": "input_audio_buffer.append", "audio": base64.b64encode(buf).decode("utf-8")},
                        )

                    if self._commit_evt.is_set():
                        self._ws_send_json(ws, {"type": "input_audio_buffer.commit"})
                        self._commit_evt.clear()
                        idle_deadline = time.time() + self.recv_timeout_sec

                    remain = max(0.02, min(0.25, idle_deadline - time.time()))
                    try:
                        msg = ws.recv(timeout=remain)
                    except TimeoutError:
                        if self._final_evt.is_set():
                            break
                        continue
                    except ConnectionClosed:
                        break

                    if isinstance(msg, bytes):
                        msg = msg.decode("utf-8", errors="ignore")
                    try:
                        obj = json.loads(msg)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        self._handle_message(obj)
                        idle_deadline = time.time() + self.recv_timeout_sec
                        if self._final_evt.is_set():
                            break
        except Exception as e:
            self._set_error(str(e))
            self._ready_evt.set()
        finally:
            self._closed_evt.set()
            self._ready_evt.set()

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._run, daemon=True, name="doubao-rtasr")
        self._thread.start()
        self._ready_evt.wait(timeout=self.open_timeout_sec + 1.0)
        return self.ready

    def append_audio(self, audio_f32_16k: np.ndarray):
        if self._stop_evt.is_set() or self._closed_evt.is_set():
            return
        pcm = self._to_pcm16(audio_f32_16k)
        if not pcm:
            return
        try:
            self._audio_q.put_nowait(pcm)
        except queue.Full:
            try:
                self._audio_q.get_nowait()
            except Exception:
                pass
            with contextlib.suppress(Exception):
                self._audio_q.put_nowait(pcm)

    def commit(self) -> str:
        if self._closed_evt.is_set():
            with self._lock:
                return (self._final_text or self._partial_text).strip()
        self._commit_evt.set()
        self._final_evt.wait(timeout=self.commit_timeout_sec)
        with self._lock:
            return (self._final_text or self._partial_text).strip()

    def close(self):
        self._stop_evt.set()
        self._final_evt.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)


class DoubaoRealtimeASREngine:
    def __init__(self):
        self.url = (settings.DOUBAO_RTASR_URL or "").strip()
        self.api_key = (settings.DOUBAO_RTASR_API_KEY or "").strip()
        self.model = (settings.DOUBAO_RTASR_MODEL or "bigmodel").strip()
        self.resource_id = (settings.DOUBAO_RTASR_RESOURCE_ID or "volc.bigasr.sauc.duration").strip()
        self.uid = (settings.DOUBAO_RTASR_UID or "voice-agent").strip()
        self.open_timeout_sec = max(2.0, float(settings.DOUBAO_RTASR_OPEN_TIMEOUT_SEC or 10))
        self.commit_timeout_sec = max(1.0, float(settings.DOUBAO_RTASR_COMMIT_TIMEOUT_SEC or 10))
        self.recv_timeout_sec = max(1.0, float(settings.DOUBAO_RTASR_RECV_TIMEOUT_SEC or 8))
        self.enable_punc = bool(settings.DOUBAO_RTASR_ENABLE_PUNC)
        self.enable_itn = bool(settings.DOUBAO_RTASR_ENABLE_ITN)
        self.enabled = bool(self.url and self.api_key and self.model)

    def start_session(self, on_partial: Callable[[str], None] | None = None) -> DoubaoRealtimeASRSession | None:
        if not self.enabled:
            return None
        s = DoubaoRealtimeASRSession(
            url=self.url,
            model=self.model,
            api_key=self.api_key,
            resource_id=self.resource_id,
            uid=self.uid,
            open_timeout_sec=self.open_timeout_sec,
            commit_timeout_sec=self.commit_timeout_sec,
            recv_timeout_sec=self.recv_timeout_sec,
            enable_punc=self.enable_punc,
            enable_itn=self.enable_itn,
            on_partial=on_partial,
        )
        return s if s.start() else None

class WhisperASR:
    def __init__(self):
        self._text_convert = lambda x: x
        self._init_text_converter()

        provider = (settings.ASR_PROVIDER or "whisper").strip().lower()
        self.provider = provider if provider in {"whisper", "xfyun_rtasr", "doubao_asr", "doubao_rtasr"} else "whisper"
        self.local = LocalWhisperEngine() if (self.provider == "whisper" or settings.ASR_FALLBACK_WHISPER) else None
        self.xfyun = XfyunRTASREngine() if self.provider == "xfyun_rtasr" else None
        self.doubao = DoubaoFlashASREngine() if self.provider == "doubao_asr" else None
        self.doubao_rt = DoubaoRealtimeASREngine() if self.provider == "doubao_rtasr" else None
        self.supports_local_partial = bool(self.local and self.local.enabled)
        self.supports_realtime_session = bool(self.doubao_rt and self.doubao_rt.enabled)

        if self.provider == "whisper":
            self.enabled = bool(self.local and self.local.enabled)
        elif self.provider == "xfyun_rtasr":
            self.enabled = bool((self.xfyun and self.xfyun.enabled) or (self.local and self.local.enabled))
        elif self.provider == "doubao_asr":
            self.enabled = bool((self.doubao and self.doubao.enabled) or (self.local and self.local.enabled))
        else:
            self.enabled = bool((self.doubao_rt and self.doubao_rt.enabled) or (self.local and self.local.enabled))

    def _init_text_converter(self):
        target = (settings.ASR_SCRIPT_TARGET or "raw").strip().lower()
        if target not in {"simplified", "traditional"}:
            return
        try:
            from opencc import OpenCC  # type: ignore
            mode = "t2s" if target == "simplified" else "s2t"
            cc = OpenCC(mode)
            self._text_convert = cc.convert
        except Exception:
            self._text_convert = lambda x: x

    def transcribe(self, audio_f32_16k: np.ndarray, language: str | None = None) -> str:
        text = ""
        if self.provider == "xfyun_rtasr" and self.xfyun and self.xfyun.enabled:
            try:
                text = self.xfyun.transcribe(audio_f32_16k)
            except Exception:
                text = ""
            if text:
                return self._text_convert(text).strip()
        elif self.provider == "doubao_asr" and self.doubao and self.doubao.enabled:
            try:
                text = self.doubao.transcribe(audio_f32_16k)
            except Exception:
                text = ""
            if text:
                return self._text_convert(text).strip()
        elif self.provider == "doubao_rtasr" and self.doubao_rt and self.doubao_rt.enabled:
            # Fallback path for one-shot calls when realtime session is unavailable.
            if self.local and self.local.enabled:
                text = self.local.transcribe(audio_f32_16k=audio_f32_16k, language=language)
                return self._text_convert(text).strip()

        if self.local and self.local.enabled:
            text = self.local.transcribe(audio_f32_16k=audio_f32_16k, language=language)
            return self._text_convert(text).strip()
        return ""

    def transcribe_partial(self, audio_f32_16k: np.ndarray, language: str | None = None) -> str:
        # Keep partial ASR cheap and low-latency by preferring local whisper.
        if self.local and self.local.enabled:
            text = self.local.transcribe(audio_f32_16k=audio_f32_16k, language=language)
            return self._text_convert(text).strip()
        return self.transcribe(audio_f32_16k=audio_f32_16k, language=language)

    def start_stream(self, on_partial: Callable[[str], None] | None = None) -> DoubaoRealtimeASRSession | None:
        if not (self.doubao_rt and self.doubao_rt.enabled):
            return None

        if on_partial:
            def wrapped(text: str):
                val = self._text_convert(text).strip()
                if val:
                    on_partial(val)
        else:
            wrapped = None

        return self.doubao_rt.start_session(on_partial=wrapped)

    def stream_append(self, session: DoubaoRealtimeASRSession | None, audio_f32_16k: np.ndarray):
        if session is None:
            return
        session.append_audio(audio_f32_16k)

    def stream_commit(self, session: DoubaoRealtimeASRSession | None) -> str:
        if session is None:
            return ""
        text = session.commit()
        return self._text_convert(text).strip()

    def stream_close(self, session: DoubaoRealtimeASRSession | None):
        if session is None:
            return
        session.close()
