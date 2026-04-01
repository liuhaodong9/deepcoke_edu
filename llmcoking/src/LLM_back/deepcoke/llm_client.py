"""
Shared LLM client — 使用 Ollama 原生 /api/chat 接口避免 OpenAI SDK 502 问题
对外仍暴露 chat() 和 chat_json() 两个函数，保持兼容。
"""
import json
import requests
from . import config

# Ollama 原生 API 地址
_OLLAMA_BASE = config.DEEPSEEK_BASE_URL.replace("/v1", "").rstrip("/")
_OLLAMA_CHAT_URL = f"{_OLLAMA_BASE}/api/chat"
_MODEL = config.DEEPSEEK_MODEL


class _StreamChunk:
    """模拟 OpenAI SDK 的 stream chunk 格式，保持 answer_generator 兼容。"""
    class _Delta:
        def __init__(self, content):
            self.content = content
    class _Choice:
        def __init__(self, delta):
            self.delta = delta
    def __init__(self, content):
        self.choices = [self._Choice(self._Delta(content))]


def chat(messages: list[dict], stream: bool = False, **kwargs):
    """
    调用 Ollama /api/chat。
    stream=True 时返回生成器（yield _StreamChunk），兼容 answer_generator。
    stream=False 时返回类似 OpenAI response 的对象。
    """
    # 清理 messages，移除不支持的字段
    clean_msgs = []
    for m in messages:
        clean_msgs.append({"role": m["role"], "content": m.get("content", "")})

    payload = {
        "model": _MODEL,
        "messages": clean_msgs,
        "stream": stream,
        "options": {"num_ctx": 4096},
    }

    if stream:
        return _stream_chat(payload)
    else:
        resp = requests.post(_OLLAMA_CHAT_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return _NonStreamResponse(data["message"].get("content", ""))


def _stream_chat(payload):
    """流式调用 Ollama，yield _StreamChunk 对象。"""
    resp = requests.post(_OLLAMA_CHAT_URL, json=payload, stream=True, timeout=120)
    resp.raise_for_status()
    for line in resp.iter_lines():
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = obj.get("message", {}).get("content", "")
        if content:
            yield _StreamChunk(content)
        if obj.get("done"):
            break


class _NonStreamResponse:
    """模拟 OpenAI SDK 非流式响应格式。"""
    class _Message:
        def __init__(self, content):
            self.content = content
    class _Choice:
        def __init__(self, message):
            self.message = message
    def __init__(self, content):
        self.choices = [self._Choice(self._Message(content))]


def chat_json(messages: list[dict], **kwargs) -> str:
    """Non-streaming call that returns the assistant content string."""
    resp = chat(messages, stream=False, **kwargs)
    return resp.choices[0].message.content.strip()
