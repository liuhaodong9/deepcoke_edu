@echo off
REM DeepCoke 启动脚本 - 使用 deepcoke conda 环境
echo ============================================
echo   DeepCoke 焦化智能问答系统
echo ============================================

call D:\anaconda3\Scripts\activate.bat deepcoke

cd /d D:\焦化机器人PC端\llmcoking\src\LLM_back

echo.
echo [1] 启动 FastAPI 后端服务...
echo     URL: http://127.0.0.1:8000
echo     Docs: http://127.0.0.1:8000/docs
echo.

uvicorn test:app --host 0.0.0.0 --port 8000 --reload
