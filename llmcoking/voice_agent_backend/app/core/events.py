# Unified event schema sent to frontend via WebSocket (JSON)
# Each message must contain "type".

# types:
# - state: {"type":"state","state":"idle|listening|thinking|speaking"}
# - asr_partial: {"type":"asr_partial","text":"...", "is_final": false}
# - asr:   {"type":"asr","text": "...", "is_final": true}
# - llm_delta: {"type":"llm_delta","text":"..."}
# - llm_done: {"type":"llm_done"}
# - tts_audio: {"type":"tts_audio","sentence_id": 1, "audio_b64":"...", "mime":"audio/wav"}
# - error: {"type":"error","message":"..."}
