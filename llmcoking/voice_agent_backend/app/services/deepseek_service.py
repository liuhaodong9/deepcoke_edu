from __future__ import annotations
import json
import re
import httpx
from typing import AsyncGenerator, List, Dict, Any
from app.core.config import settings

SENT_SPLIT_RE = re.compile(r'(?<=[。！？.!?])\s+')

def split_into_sentences(buffer: str) -> tuple[list[str], str]:
    """Return (complete_sentences, remaining_buffer)."""
    # First, split by punctuation with following whitespace.
    parts = SENT_SPLIT_RE.split(buffer)
    if len(parts) <= 1:
        return [], buffer

    # If buffer ends with punctuation, all are complete; else last is incomplete.
    if re.search(r'[。！？.!?]\s*$', buffer):
        return [p for p in parts if p], ""
    else:
        return [p for p in parts[:-1] if p], parts[-1]

async def deepseek_stream_chat(messages: List[Dict[str, Any]]) -> AsyncGenerator[str, None]:
    """Yield text deltas from DeepSeek Chat Completions (OpenAI-compatible SSE)."""
    api_key = (settings.DEEPSEEK_API_KEY or "").strip()
    if (not api_key) or (api_key == "your_deepseek_key_here"):
        raise RuntimeError("Invalid DEEPSEEK_API_KEY in .env. Set a real key and restart backend.")

    url = settings.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"model": settings.DEEPSEEK_MODEL, "messages": messages, "stream": True}

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0]["delta"]
                    chunk = delta.get("content") or ""
                    if chunk:
                        yield chunk
                except Exception:
                    continue
