@echo off
title DeepCoke Text Backend
cd /d "%~dp0src\LLM_back"
python -m uvicorn test:app --host 0.0.0.0 --port 8000 --reload
pause
