"""
VLM 客户端 (Phase 2 图表理解) — 给视觉模型(Qwen2.5-VL)发「图像 + 文字」请求。

双模式,env 控制(同 llm_client 风格):
  VLM_MODE=ollama  → Ollama 原生 /api/chat,图像走 messages[].images (base64 列表)
  VLM_MODE=openai  → OpenAI 兼容 /v1/chat/completions,图像走 content[].image_url (data URI)

对外只暴露 describe_image(image_bytes, prompt) -> str。
不用 OpenAI SDK(用户规则),手撸 requests。
"""
import os
import json
import base64
import requests

from . import config

VLM_MODE = config.VLM_MODE
_MODEL = config.VLM_MODEL
_TIMEOUT = float(os.getenv("VLM_TIMEOUT", "180"))

# Ollama 端点(去 /v1)
_OLLAMA_BASE = config.VLM_BASE_URL.replace("/v1", "").rstrip("/")
_OLLAMA_CHAT_URL = f"{_OLLAMA_BASE}/api/chat"

# OpenAI 兼容端点(留 /v1)
_OPENAI_BASE = config.VLM_BASE_URL
if not _OPENAI_BASE.rstrip("/").endswith("/v1"):
    _OPENAI_BASE = _OPENAI_BASE.rstrip("/") + "/v1"
_OPENAI_CHAT_URL = _OPENAI_BASE.rstrip("/") + "/chat/completions"
_OPENAI_API_KEY = config.VLM_API_KEY


def _b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("ascii")


def _ollama_describe(image_bytes: bytes, prompt: str, **kwargs) -> str:
    payload = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt, "images": [_b64(image_bytes)]}],
        "stream": False,
        "options": {"temperature": kwargs.get("temperature", 0.2)},
    }
    resp = requests.post(_OLLAMA_CHAT_URL, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["message"].get("content", "").strip()


def _openai_describe(image_bytes: bytes, prompt: str, mime: str = "image/png", **kwargs) -> str:
    data_uri = f"data:{mime};base64,{_b64(image_bytes)}"
    payload = {
        "model": _MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }],
        "stream": False,
        "temperature": kwargs.get("temperature", 0.2),
    }
    if kwargs.get("max_tokens"):
        payload["max_tokens"] = kwargs["max_tokens"]
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {_OPENAI_API_KEY}"}
    resp = requests.post(_OPENAI_CHAT_URL, json=payload, headers=headers, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"].get("content", "").strip()


def describe_image(image_bytes: bytes, prompt: str, mime: str = "image/png", **kwargs) -> str:
    """给视觉模型发图 + prompt,返回文本描述。按 VLM_MODE 分发。"""
    if VLM_MODE == "openai":
        return _openai_describe(image_bytes, prompt, mime=mime, **kwargs)
    return _ollama_describe(image_bytes, prompt, **kwargs)


def vlm_available() -> bool:
    """探活:能连上 VLM 端点就返回 True(不验证模型是否在)。"""
    try:
        if VLM_MODE == "openai":
            r = requests.get(_OPENAI_BASE.rstrip("/") + "/models",
                             headers={"Authorization": f"Bearer {_OPENAI_API_KEY}"}, timeout=8)
        else:
            r = requests.get(_OLLAMA_BASE + "/api/tags", timeout=8)
        return r.status_code == 200
    except Exception:
        return False
