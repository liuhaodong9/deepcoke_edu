"""
Shared LLM client — 同时支持两种后端，env 控制：

  LLM_MODE=ollama   (默认)  → Ollama 原生 /api/chat
  LLM_MODE=openai            → OpenAI 兼容 /v1/chat/completions（vLLM / DeepSeek API / OpenAI）

接口 chat() 和 chat_json() 对外签名不变，answer_generator 等调用方零改动。

设计:
- 不用 OpenAI Python SDK（用户规则：本地 Ollama 调 SDK 会 502；vLLM 端 SDK 没必要装）
- 手撸 SSE 解析（OpenAI 模式），跟 Ollama 解析风格一致
- 流式 chunk 模拟 OpenAI SDK 的 choices[0].delta.content 结构
"""
import json
import os
import requests

from . import config

# ── 模式 ────────────────────────────────────────────────────────────
LLM_MODE = os.getenv("LLM_MODE", "ollama").lower().strip()

# Ollama 端点（去掉末尾 /v1 如果带的话）
_OLLAMA_BASE = config.DEEPSEEK_BASE_URL.replace("/v1", "").rstrip("/")
_OLLAMA_CHAT_URL = f"{_OLLAMA_BASE}/api/chat"

# OpenAI 兼容端点（保留 /v1）
_OPENAI_BASE = config.DEEPSEEK_BASE_URL
if not _OPENAI_BASE.endswith("/v1") and not _OPENAI_BASE.endswith("/v1/"):
    # 容错：用户配置可能漏掉 /v1
    _OPENAI_BASE = _OPENAI_BASE.rstrip("/") + "/v1"
_OPENAI_CHAT_URL = _OPENAI_BASE.rstrip("/") + "/chat/completions"
_OPENAI_API_KEY = config.DEEPSEEK_API_KEY  # vLLM 默认接受任意非空字符串

_MODEL = config.DEEPSEEK_MODEL
_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "180"))


# ── 兼容 OpenAI SDK 的轻量返回对象 ───────────────────────────────────
class _StreamChunk:
    class _Delta:
        def __init__(self, content):
            self.content = content
    class _Choice:
        def __init__(self, delta):
            self.delta = delta
    def __init__(self, content):
        self.choices = [self._Choice(self._Delta(content))]


class _NonStreamResponse:
    class _Message:
        def __init__(self, content):
            self.content = content
    class _Choice:
        def __init__(self, message):
            self.message = message
    def __init__(self, content):
        self.choices = [self._Choice(self._Message(content))]


# ── Ollama 原生 ────────────────────────────────────────────────────
def _ollama_chat(messages, stream, **kwargs):
    clean_msgs = [{"role": m["role"], "content": m.get("content", "")} for m in messages]
    payload = {
        "model": _MODEL,
        "messages": clean_msgs,
        "stream": stream,
        "options": {"num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "4096"))},
    }
    if stream:
        return _ollama_stream(payload)
    resp = requests.post(_OLLAMA_CHAT_URL, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return _NonStreamResponse(data["message"].get("content", ""))


def _ollama_stream(payload):
    resp = requests.post(_OLLAMA_CHAT_URL, json=payload, stream=True, timeout=_TIMEOUT)
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


# ── OpenAI 兼容（vLLM / DeepSeek API / OpenAI） ──────────────────────
def _openai_headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_OPENAI_API_KEY}",
    }


def _openai_chat(messages, stream, **kwargs):
    clean_msgs = [{"role": m["role"], "content": m.get("content", "")} for m in messages]
    payload = {
        "model": _MODEL,
        "messages": clean_msgs,
        "stream": stream,
    }
    # 透传 temperature / max_tokens 等
    for k in ("temperature", "max_tokens", "top_p"):
        if k in kwargs and kwargs[k] is not None:
            payload[k] = kwargs[k]

    if stream:
        return _openai_stream(payload)
    resp = requests.post(_OPENAI_CHAT_URL, json=payload, headers=_openai_headers(), timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"].get("content", "")
    return _NonStreamResponse(content)


def _openai_stream(payload):
    """解析 OpenAI/vLLM 的 SSE 流：每行 `data: {...}` 或 `data: [DONE]`。"""
    resp = requests.post(_OPENAI_CHAT_URL, json=payload, headers=_openai_headers(),
                         stream=True, timeout=_TIMEOUT)
    resp.raise_for_status()
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        # SSE 行格式：data: {...}
        if not line.startswith("data:"):
            continue
        payload_str = line[5:].strip()
        if payload_str == "[DONE]":
            break
        try:
            obj = json.loads(payload_str)
        except json.JSONDecodeError:
            continue
        try:
            delta = obj["choices"][0].get("delta") or {}
        except (KeyError, IndexError):
            continue
        content = delta.get("content")
        if content:
            yield _StreamChunk(content)


# ── 对外接口（保持原签名） ──────────────────────────────────────────
def chat(messages: list[dict], stream: bool = False, **kwargs):
    """统一入口，按 LLM_MODE 分发。返回值与原版一致。"""
    if LLM_MODE == "openai":
        return _openai_chat(messages, stream, **kwargs)
    return _ollama_chat(messages, stream, **kwargs)


def chat_json(messages: list[dict], **kwargs) -> str:
    """Non-streaming call that returns the assistant content string."""
    resp = chat(messages, stream=False, **kwargs)
    return resp.choices[0].message.content.strip()


# ── Tool calling (OpenAI function calling 兼容,仅 LLM_MODE=openai 支持) ─────────────
def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    tool_choice: str = "auto",
    **kwargs,
) -> dict:
    """
    支持 tool calling 的 chat 接口(non-streaming)。

    返回 dict:
      {
        "content": str | None,           # 模型生成的文本(可能为空)
        "tool_calls": [                  # 模型要调用的工具列表(可能为空)
          {"name": "...", "arguments": {...}, "id": "..."},
          ...
        ],
        "finish_reason": str,            # "stop" | "tool_calls" | "length"
      }
    """
    if LLM_MODE != "openai":
        raise NotImplementedError(
            "chat_with_tools 只支持 LLM_MODE=openai(vllm/OpenAI),Ollama 暂不支持"
        )

    clean_msgs = []
    for m in messages:
        msg = {"role": m["role"]}
        if "content" in m:
            msg["content"] = m["content"]
        if "tool_calls" in m:
            msg["tool_calls"] = m["tool_calls"]
        if "tool_call_id" in m:
            msg["tool_call_id"] = m["tool_call_id"]
        if "name" in m:
            msg["name"] = m["name"]
        clean_msgs.append(msg)

    payload = {
        "model": _MODEL,
        "messages": clean_msgs,
        "stream": False,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    for k in ("temperature", "max_tokens", "top_p"):
        if k in kwargs and kwargs[k] is not None:
            payload[k] = kwargs[k]

    resp = requests.post(
        _OPENAI_CHAT_URL, json=payload, headers=_openai_headers(), timeout=_TIMEOUT
    )
    resp.raise_for_status()
    data = resp.json()
    choice = data["choices"][0]
    msg = choice.get("message", {}) or {}

    tool_calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {}) or {}
        args_raw = fn.get("arguments", "{}")
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
        except json.JSONDecodeError:
            args = {}
        tool_calls.append({
            "id": tc.get("id", ""),
            "name": fn.get("name", ""),
            "arguments": args,
        })

    return {
        "content": msg.get("content"),
        "tool_calls": tool_calls,
        "finish_reason": choice.get("finish_reason", ""),
    }
