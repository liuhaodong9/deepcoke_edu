import os
from dotenv import load_dotenv

load_dotenv()

def getenv(key: str, default: str | None = None) -> str | None:
    v = os.getenv(key)
    return v if v is not None and v != "" else default

class Settings:
    # DeepSeek
    DEEPSEEK_API_KEY = getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE_URL = getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    DEEPSEEK_MODEL = getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # Whisper
    WHISPER_MODEL_SIZE = getenv("WHISPER_MODEL_SIZE", "small")
    WHISPER_DEVICE = getenv("WHISPER_DEVICE", "auto")
    WHISPER_COMPUTE_TYPE = getenv("WHISPER_COMPUTE_TYPE", "auto")
    WHISPER_LANGUAGE = getenv("WHISPER_LANGUAGE", "zh")  # zh|en|ja|...
    ASR_SCRIPT_TARGET = getenv("ASR_SCRIPT_TARGET", "simplified")  # simplified|traditional|raw
    ASR_PROVIDER = getenv("ASR_PROVIDER", "whisper")  # whisper|xfyun_rtasr|doubao_asr|doubao_rtasr
    ASR_FALLBACK_WHISPER = (getenv("ASR_FALLBACK_WHISPER", "true").lower() == "true")
    ASR_CONTEXT_WINDOW_TURNS = int(getenv("ASR_CONTEXT_WINDOW_TURNS", "6"))

    # Streaming partial ASR
    ASR_PARTIAL_ENABLED = (getenv("ASR_PARTIAL_ENABLED", "true").lower() == "true")
    ASR_PARTIAL_INTERVAL_MS = int(getenv("ASR_PARTIAL_INTERVAL_MS", "700"))
    ASR_PARTIAL_MIN_AUDIO_MS = int(getenv("ASR_PARTIAL_MIN_AUDIO_MS", "640"))
    ASR_PARTIAL_WINDOW_SEC = float(getenv("ASR_PARTIAL_WINDOW_SEC", "10"))
    ASR_PARTIAL_ALLOW_REMOTE_PROVIDER = (getenv("ASR_PARTIAL_ALLOW_REMOTE_PROVIDER", "false").lower() == "true")

    # iFlytek Real-Time ASR (RTASR)
    XFYUN_APP_ID = getenv("XFYUN_APP_ID", "")
    XFYUN_API_KEY = getenv("XFYUN_API_KEY", "")
    XFYUN_RTASR_URL = getenv("XFYUN_RTASR_URL", "wss://rtasr.xfyun.cn/v1/ws")
    XFYUN_RTASR_LANG = getenv("XFYUN_RTASR_LANG", "cn")  # cn|en
    XFYUN_RTASR_CHUNK_MS = int(getenv("XFYUN_RTASR_CHUNK_MS", "40"))
    XFYUN_RTASR_RECV_TIMEOUT_SEC = float(getenv("XFYUN_RTASR_RECV_TIMEOUT_SEC", "5"))

    # Doubao / Volcengine BigASR (flash API, OpenSpeech)
    DOUBAO_API_APP_KEY = getenv("DOUBAO_API_APP_KEY", "")
    DOUBAO_API_ACCESS_KEY = getenv("DOUBAO_API_ACCESS_KEY", "")
    DOUBAO_API_RESOURCE_ID = getenv("DOUBAO_API_RESOURCE_ID", "volc.bigasr.auc_turbo")
    DOUBAO_ASR_ENDPOINT = getenv(
        "DOUBAO_ASR_ENDPOINT", "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
    )
    DOUBAO_ASR_MODEL_NAME = getenv("DOUBAO_ASR_MODEL_NAME", "bigmodel")
    DOUBAO_ASR_UID = getenv("DOUBAO_ASR_UID", "voice-agent")
    DOUBAO_ASR_TIMEOUT_SEC = float(getenv("DOUBAO_ASR_TIMEOUT_SEC", "30"))
    DOUBAO_ASR_ENABLE_PUNC = (getenv("DOUBAO_ASR_ENABLE_PUNC", "true").lower() == "true")
    DOUBAO_ASR_ENABLE_ITN = (getenv("DOUBAO_ASR_ENABLE_ITN", "true").lower() == "true")

    # Doubao Realtime ASR (WebSocket, low-latency partial revision)
    DOUBAO_RTASR_URL = getenv("DOUBAO_RTASR_URL", "wss://ai-gateway.vei.volces.com/v1/realtime")
    DOUBAO_RTASR_API_KEY = getenv("DOUBAO_RTASR_API_KEY", "")
    DOUBAO_RTASR_MODEL = getenv("DOUBAO_RTASR_MODEL", "bigmodel")
    DOUBAO_RTASR_RESOURCE_ID = getenv("DOUBAO_RTASR_RESOURCE_ID", "volc.bigasr.sauc.duration")
    DOUBAO_RTASR_UID = getenv("DOUBAO_RTASR_UID", "voice-agent")
    DOUBAO_RTASR_OPEN_TIMEOUT_SEC = float(getenv("DOUBAO_RTASR_OPEN_TIMEOUT_SEC", "10"))
    DOUBAO_RTASR_COMMIT_TIMEOUT_SEC = float(getenv("DOUBAO_RTASR_COMMIT_TIMEOUT_SEC", "10"))
    DOUBAO_RTASR_RECV_TIMEOUT_SEC = float(getenv("DOUBAO_RTASR_RECV_TIMEOUT_SEC", "8"))
    DOUBAO_RTASR_ENABLE_PUNC = (getenv("DOUBAO_RTASR_ENABLE_PUNC", "true").lower() == "true")
    DOUBAO_RTASR_ENABLE_ITN = (getenv("DOUBAO_RTASR_ENABLE_ITN", "true").lower() == "true")

    # Simple voice websocket audio profile (recommended for realtime ASR)
    SIMPLE_AUDIO_SAMPLE_RATE = int(getenv("SIMPLE_AUDIO_SAMPLE_RATE", "16000"))
    SIMPLE_AUDIO_CHANNELS = int(getenv("SIMPLE_AUDIO_CHANNELS", "1"))
    SIMPLE_AUDIO_BITS_PER_SAMPLE = int(getenv("SIMPLE_AUDIO_BITS_PER_SAMPLE", "16"))
    SIMPLE_AUDIO_FRAME_MS = int(getenv("SIMPLE_AUDIO_FRAME_MS", "40"))

    # VAD
    VAD_THRESHOLD = float(getenv("VAD_THRESHOLD", "0.5"))
    VAD_MIN_SPEECH_MS = int(getenv("VAD_MIN_SPEECH_MS", "250"))
    VAD_MIN_SILENCE_MS = int(getenv("VAD_MIN_SILENCE_MS", "500"))

    # Spark-TTS (CLI mode)
    TTS_PROVIDER = getenv("TTS_PROVIDER", "doubao_tts")  # doubao_tts|spark_tts

    # Doubao TTS (OpenSpeech HTTP)
    DOUBAO_TTS_ENDPOINT = getenv("DOUBAO_TTS_ENDPOINT", "https://openspeech.bytedance.com/api/v3/tts/unidirectional")
    DOUBAO_TTS_APP_ID = getenv("DOUBAO_TTS_APP_ID", "")
    DOUBAO_TTS_ACCESS_KEY = getenv("DOUBAO_TTS_ACCESS_KEY", "")
    DOUBAO_TTS_RESOURCE_ID = getenv("DOUBAO_TTS_RESOURCE_ID", "volc.service_type.10029")
    DOUBAO_TTS_UID = getenv("DOUBAO_TTS_UID", "voice-agent")
    DOUBAO_TTS_VOICE_TYPE = getenv("DOUBAO_TTS_VOICE_TYPE", "BV001_streaming")
    DOUBAO_TTS_ENCODING = getenv("DOUBAO_TTS_ENCODING", "mp3")  # mp3|wav|pcm
    DOUBAO_TTS_SPEED_RATIO = float(getenv("DOUBAO_TTS_SPEED_RATIO", "1.0"))
    DOUBAO_TTS_VOLUME_RATIO = float(getenv("DOUBAO_TTS_VOLUME_RATIO", "1.0"))
    DOUBAO_TTS_PITCH_RATIO = float(getenv("DOUBAO_TTS_PITCH_RATIO", "1.0"))
    DOUBAO_TTS_EMOTION = getenv("DOUBAO_TTS_EMOTION", "")
    DOUBAO_TTS_EMOTION_SCALE = float(getenv("DOUBAO_TTS_EMOTION_SCALE", "1.0"))
    DOUBAO_TTS_SILENCE_DURATION_MS = int(getenv("DOUBAO_TTS_SILENCE_DURATION_MS", "125"))
    DOUBAO_TTS_WITH_FRONTEND = (getenv("DOUBAO_TTS_WITH_FRONTEND", "true").lower() == "true")
    DOUBAO_TTS_FRONTEND_TYPE = getenv("DOUBAO_TTS_FRONTEND_TYPE", "unitTson")
    DOUBAO_TTS_TIMEOUT_SEC = float(getenv("DOUBAO_TTS_TIMEOUT_SEC", "20"))

    # Spark-TTS (CLI mode)
    SPARKTTS_PYTHON = getenv("SPARKTTS_PYTHON", "")
    SPARKTTS_WORKDIR = getenv("SPARKTTS_WORKDIR", "")
    SPARKTTS_MODEL_DIR = getenv("SPARKTTS_MODEL_DIR", "")
    SPARKTTS_DEVICE = getenv("SPARKTTS_DEVICE", "0")
    SPARKTTS_PROMPT_TEXT = getenv("SPARKTTS_PROMPT_TEXT", "")
    SPARKTTS_PROMPT_SPEECH_PATH = getenv("SPARKTTS_PROMPT_SPEECH_PATH", "")

    ENABLE_SERVER_TTS = (getenv("ENABLE_SERVER_TTS", "true").lower() == "true")

settings = Settings()
