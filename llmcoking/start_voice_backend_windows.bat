@echo off
title DeepCoke Voice Backend
cd /d "%~dp0voice_agent_backend"

if not exist ".venv" (
    echo [1/6] Creating Python virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate

echo [2/6] Upgrading pip...
python -m pip install -U pip

echo [3/6] Installing voice backend package...
pip install -e .

echo [4/6] Installing ASR/VAD packages...
pip install faster-whisper silero-vad

if not exist ".env" (
    echo [5/6] Creating .env from template...
    copy .env.example .env >nul
    echo Please edit voice_agent_backend\.env and set DEEPSEEK_API_KEY.
)

echo [6/6] Starting voice backend at http://localhost:8001
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
pause
