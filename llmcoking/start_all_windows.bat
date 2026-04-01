@echo off
title DeepCoke All Services Launcher
echo ============================================
echo   DeepCoke - Starting All Services
echo ============================================
echo.

:: 1. Text Backend (port 8000)
echo [1/3] Starting Text Backend (port 8000)...
start "DeepCoke Text Backend" cmd /k "cd /d %~dp0src\LLM_back && python -m uvicorn test:app --host 0.0.0.0 --port 8000 --reload"

:: 2. Voice Backend (port 8001)
echo [2/3] Starting Voice Backend (port 8001)...
start "DeepCoke Voice Backend" cmd /k "cd /d %~dp0voice_agent_backend && call .venv\Scripts\activate && uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"

:: 3. Frontend (port 8080)
echo [3/3] Starting Frontend (port 8080)...
start "DeepCoke Frontend" cmd /k "cd /d %~dp0 && npm run serve"

echo.
echo ============================================
echo   All services are launching...
echo   Frontend:  http://localhost:8080
echo   Text API:  http://localhost:8000
echo   Voice API: http://localhost:8001
echo ============================================
echo.
pause
