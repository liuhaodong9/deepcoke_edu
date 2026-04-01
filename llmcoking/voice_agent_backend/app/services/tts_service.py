from __future__ import annotations
import base64
import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings

@dataclass
class TTSResult:
    # Kept field name for backward compatibility with existing state_manager usage.
    wav_bytes: bytes
    mime: str = "audio/wav"

class _SparkTTSProvider:
    """Local Spark-TTS CLI provider."""
    def __init__(self):
        self.enabled = (
            settings.ENABLE_SERVER_TTS
            and bool(settings.SPARKTTS_PYTHON)
            and bool(settings.SPARKTTS_WORKDIR)
            and bool(settings.SPARKTTS_MODEL_DIR)
        )

    def synth(self, text: str) -> Optional[TTSResult]:
        if not self.enabled:
            return None

        save_dir = Path(settings.SPARKTTS_WORKDIR) / "example" / "results" / f"agent_{int(time.time()*1000)}"
        save_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            settings.SPARKTTS_PYTHON,
            "-m",
            "cli.inference",
            "--text",
            text,
            "--device",
            str(settings.SPARKTTS_DEVICE),
            "--save_dir",
            str(save_dir),
            "--model_dir",
            str(settings.SPARKTTS_MODEL_DIR),
        ]

        # Optional cloning prompt
        if settings.SPARKTTS_PROMPT_TEXT:
            cmd += ["--prompt_text", settings.SPARKTTS_PROMPT_TEXT]
        if settings.SPARKTTS_PROMPT_SPEECH_PATH:
            cmd += ["--prompt_speech_path", settings.SPARKTTS_PROMPT_SPEECH_PATH]

        # Run in Spark-TTS repo directory so `cli` module is found
        proc = subprocess.run(
            cmd,
            cwd=settings.SPARKTTS_WORKDIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode != 0:
            # leave logs for debugging
            return None

        # Find newest wav in save_dir
        wavs = sorted(save_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not wavs:
            return None
        wav_bytes = wavs[0].read_bytes()
        return TTSResult(wav_bytes=wav_bytes)


class DoubaoTTSHTTP:
    """Doubao OpenSpeech HTTP TTS provider (supports emotional params)."""

    def __init__(self):
        self.endpoint = (settings.DOUBAO_TTS_ENDPOINT or "").strip()
        self.app_id = (settings.DOUBAO_TTS_APP_ID or "").strip()
        self.access_key = (settings.DOUBAO_TTS_ACCESS_KEY or "").strip()
        self.resource_id = (settings.DOUBAO_TTS_RESOURCE_ID or "").strip()
        self.uid = (settings.DOUBAO_TTS_UID or "voice-agent").strip()
        self.voice_type = (settings.DOUBAO_TTS_VOICE_TYPE or "BV001_streaming").strip()
        self.encoding = (settings.DOUBAO_TTS_ENCODING or "mp3").strip().lower()
        self.speed_ratio = float(settings.DOUBAO_TTS_SPEED_RATIO)
        self.volume_ratio = float(settings.DOUBAO_TTS_VOLUME_RATIO)
        self.pitch_ratio = float(settings.DOUBAO_TTS_PITCH_RATIO)
        self.emotion = (settings.DOUBAO_TTS_EMOTION or "").strip()
        self.emotion_scale = float(settings.DOUBAO_TTS_EMOTION_SCALE)
        self.silence_duration_ms = int(settings.DOUBAO_TTS_SILENCE_DURATION_MS)
        self.with_frontend = bool(settings.DOUBAO_TTS_WITH_FRONTEND)
        self.frontend_type = (settings.DOUBAO_TTS_FRONTEND_TYPE or "unitTson").strip()
        self.timeout_sec = max(5.0, float(settings.DOUBAO_TTS_TIMEOUT_SEC or 20))
        self._is_v1 = "/api/v1/" in self.endpoint
        self.enabled = (
            settings.ENABLE_SERVER_TTS
            and bool(self.endpoint)
            and bool(self.app_id)
            and bool(self.access_key)
        )

    @staticmethod
    def _decode_b64(val: str) -> bytes:
        if not isinstance(val, str):
            return b""
        s = val.strip()
        if not s:
            return b""
        try:
            return base64.b64decode(s)
        except Exception:
            return b""

    @staticmethod
    def _mime_for_encoding(enc: str) -> str:
        e = (enc or "").strip().lower()
        if e == "mp3":
            return "audio/mpeg"
        if e == "wav":
            return "audio/wav"
        if e == "pcm":
            return "audio/pcm"
        return "application/octet-stream"

    @staticmethod
    def _obj_error_message(obj: object) -> str:
        if not isinstance(obj, dict):
            return ""
        t = str(obj.get("type") or "").strip().lower()
        if t == "error":
            err = obj.get("error", {})
            if isinstance(err, dict):
                return f"{err.get('code', '')} {err.get('message', '')}".strip()
            return str(err).strip()

        code = obj.get("code")
        if code not in {None, 0, "0", 200, "200", 3000, "3000"}:
            msg = obj.get("message") or obj.get("msg") or obj.get("error") or ""
            return f"{code} {msg}".strip()
        return ""

    @classmethod
    def _extract_audio_chunks(cls, node: object) -> list[bytes]:
        chunks: list[bytes] = []

        def walk(x: object):
            if isinstance(x, dict):
                for k, v in x.items():
                    lk = str(k).lower()
                    if lk in {"audio", "audio_data", "audio_base64", "data"} and isinstance(v, str):
                        b = cls._decode_b64(v)
                        if b:
                            chunks.append(b)
                            continue
                    if isinstance(v, (dict, list)):
                        walk(v)
            elif isinstance(x, list):
                for it in x:
                    walk(it)

        walk(node)
        return chunks

    def _build_payload(self, text: str) -> dict:
        audio_cfg = {
            "voice_type": self.voice_type,
            "encoding": self.encoding,
            "speed_ratio": self.speed_ratio,
            "volume_ratio": self.volume_ratio,
            "pitch_ratio": self.pitch_ratio,
        }
        if self.emotion:
            audio_cfg["emotion"] = self.emotion
            audio_cfg["emotion_scale"] = self.emotion_scale

        req_cfg = {
            "reqid": str(uuid.uuid4()),
            "text": text,
            "text_type": "plain",
            "operation": "query",
            "silence_duration": str(self.silence_duration_ms),
            "with_frontend": "1" if self.with_frontend else "0",
            "frontend_type": self.frontend_type,
        }

        payload = {
            "user": {"uid": self.uid},
            "audio": audio_cfg,
            "request": req_cfg,
        }

        if self._is_v1:
            payload["app"] = {
                "appid": self.app_id,
                "token": self.access_key,
                "cluster": "volcano_tts",
            }

        return payload

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._is_v1:
            headers["Authorization"] = f"Bearer;{self.access_key}"
        else:
            headers["X-Api-App-Id"] = self.app_id
            headers["X-Api-Access-Key"] = self.access_key
            if self.resource_id:
                headers["X-Api-Resource-Id"] = self.resource_id
            headers["X-Api-Request-Id"] = str(uuid.uuid4())
        return headers

    def _parse_json_lines_audio(self, raw_bytes: bytes) -> bytes:
        if not raw_bytes:
            return b""
        text = raw_bytes.decode("utf-8", errors="ignore").strip()
        if not text:
            return b""

        audio_chunks: list[bytes] = []

        # Try parse as one JSON payload first.
        try:
            obj = json.loads(text)
            err = self._obj_error_message(obj)
            if err:
                raise RuntimeError(f"Doubao TTS API error: {err}")
            audio_chunks.extend(self._extract_audio_chunks(obj))
        except json.JSONDecodeError:
            # Not a single JSON object — parse line-based JSON/SSE payloads.
            for line in text.splitlines():
                s = line.strip()
                if not s:
                    continue
                if s.startswith("data:"):
                    s = s[5:].strip()
                if not s or s == "[DONE]":
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                err = self._obj_error_message(obj)
                if err:
                    raise RuntimeError(f"Doubao TTS API error: {err}")
                audio_chunks.extend(self._extract_audio_chunks(obj))

        if not audio_chunks:
            return b""
        return b"".join(audio_chunks)

    def synth(self, text: str) -> Optional[TTSResult]:
        if not self.enabled:
            return None
        txt = (text or "").strip()
        if not txt:
            return None

        payload = self._build_payload(txt)
        headers = self._build_headers()

        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                resp = client.post(self.endpoint, json=payload, headers=headers)
                resp.raise_for_status()
        except Exception:
            return None

        ctype = (resp.headers.get("content-type") or "").lower()
        if ctype.startswith("audio/"):
            data = resp.content
            if not data:
                return None
            return TTSResult(wav_bytes=data, mime=ctype.split(";")[0].strip())

        data = self._parse_json_lines_audio(resp.content)
        if not data:
            return None
        return TTSResult(wav_bytes=data, mime=self._mime_for_encoding(self.encoding))


class SparkTTSCLI:
    """Unified TTS entry used by state_manager."""
    def __init__(self):
        provider = (settings.TTS_PROVIDER or "doubao_tts").strip().lower()
        if provider == "spark_tts":
            self._impl = _SparkTTSProvider()
        else:
            self._impl = DoubaoTTSHTTP()
        self.enabled = bool(self._impl.enabled)

    def synth(self, text: str) -> Optional[TTSResult]:
        return self._impl.synth(text) if self.enabled else None


def b64encode_wav(wav_bytes: bytes) -> str:
    return base64.b64encode(wav_bytes).decode("ascii")
