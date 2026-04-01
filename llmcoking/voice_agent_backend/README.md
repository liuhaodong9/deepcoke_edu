# Voice Agent Backend (FastAPI)

## 1) Create env and install
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -U pip
pip install -e .
```

### Optional (recommended) packages
```bash
pip install faster-whisper
pip install silero-vad
```

> If you do not install `silero-vad`, the backend will try to load Silero VAD via `torch.hub` (it may download weights).
> If you do not install `faster-whisper`, ASR will be disabled.

## 2) Configure
```bash
cp .env.example .env
# then edit .env
```

## 3) Run
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend endpoints:
- WebSocket: `ws://localhost:8000/ws/agent`
- Health: `GET http://localhost:8000/health`
