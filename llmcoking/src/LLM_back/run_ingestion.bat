@echo off
REM DeepCoke 文献导入脚本 - 处理236篇PDF文献
echo ============================================
echo   DeepCoke 文献导入工具
echo   处理 Coal blend paper 中的所有PDF文献
echo ============================================

call D:\anaconda3\Scripts\activate.bat deepcoke

cd /d D:\焦化机器人PC端\llmcoking\src\LLM_back

echo.
echo [Step 1] 解析PDF、提取元数据、分块、存入ChromaDB...
python -m deepcoke.ingestion.run_ingestion

echo.
echo [Step 2] 构建知识图谱 (需要先启动Neo4j)...
echo 如果Neo4j未运行，可跳过此步骤，系统仍可正常工作（仅使用向量检索）
set /p BUILD_KG="是否构建知识图谱? (y/N): "
if /i "%BUILD_KG%"=="y" (
    python -m deepcoke.knowledge_graph.builder
)

echo.
echo 导入完成!
pause
