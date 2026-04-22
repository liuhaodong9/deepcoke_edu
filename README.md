# DeepCoke 智能焦化决策平台 — 精简教学版 (edu-lite-langgraph)

焦化配煤智能问答系统：配煤优化、文献 RAG 检索、全双工语音对话。主干逻辑全本地部署，LLM 走本地 Ollama，可选豆包 TTS/RTASR 做更好的语音体验。

本分支 `edu-lite-langgraph` 相对 `master` 的特点：

- **去掉** 04-07 版引入的数字孪生视频 UI 与右侧煤仓面板，界面更干净
- **保留并采用** 04-14 的 LangGraph + LLM Supervisor 智能路由（声明式 Agent 图，替代原硬编码 if/else）
- **保留** 语音后端的豆包 TTS 欢迎语：进入语音对话页即自动朗读「您好，我是焦化大语言智能问答与分析系统 DeepCoke……」

## 架构

```
FastAPI (test.py:8000) → pipeline_graph.py (LangGraph StateGraph)
  └── Supervisor LLM 路由（关键词快速通道 + LLM 决策 fallback）
        ├── coal_price      煤价查询
        ├── oven_control    焦炉操作
        ├── optimization    配煤优化 / 质量预测
        ├── data_management 煤样 CRUD / CNN 预测
        ├── knowledge_qa    文献 RAG + 因果推理
        └── simple_chat     闲聊

Voice WS (voice_agent_backend:8001)
  └── Silero VAD → Whisper/豆包 RTASR → DeepSeek/Ollama → 豆包 TTS
```

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Anaconda / Miniconda | latest | Python 环境管理 |
| Node.js | ≥ 14 | 前端 |
| MySQL | 8.0 | 会话存储 |
| Ollama | latest | 本地 LLM |

## 快速开始

### 1. 克隆并切到本分支

```bash
git clone -b edu-lite-langgraph https://github.com/liuhaodong9/deepcoke_edu.git
cd deepcoke_edu
```

### 2. Python 环境

```bash
cd llmcoking
conda env create -f environment.yml
conda activate deepcoke
pip install -r requirements.txt
```

Windows 上如果后续出现某些包 DLL 加载失败（torch / cryptography / ctranslate2），通常是 wheel 和系统 VC++ Redistributable 版本不匹配。已验证可跑的稳定组合：

```bash
pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu
pip install "cryptography==42.0.8"
pip install "ctranslate2==4.4.0" "faster-whisper==1.0.3" "setuptools<80"
```

### 3. 前端依赖

```bash
cd llmcoking
npm install
```

Windows 下 Node.js 未加入 PATH 时：

```cmd
set PATH=%PATH%;C:\Program Files\nodejs
```

### 4. MySQL

```sql
CREATE DATABASE IF NOT EXISTS chat_db DEFAULT CHARACTER SET utf8mb4;
```

默认连接串：`root:123456@127.0.0.1:3306/chat_db`。账号密码不同时改 `llmcoking/src/LLM_back/test.py` 顶部的 `DATABASE_URL`。

### 5. 本地 LLM

```bash
ollama pull qwen3:8b
```

### 6. 向量库数据（可选）

文献 RAG 需要 ChromaDB 向量库。两种方式选其一：

- **推荐**：从仓库 [Releases](../../releases) 下载 `chromadb_data.tar.gz`，解压到 `llmcoking/src/LLM_back/deepcoke/data/chromadb/`
- **自行摄入**：把 PDF 放入 `llmcoking/src/LLM_back/` 后运行 `python fast_ingest.py`

### 7. 语音后端配置（可选）

语音对话需要豆包 TTS 和 DeepSeek/豆包 RTASR 的 API Key。复制示例文件并填入：

```bash
cd llmcoking/voice_agent_backend
cp .env.example .env
# 编辑 .env，填入：
#   DEEPSEEK_API_KEY=...
#   DOUBAO_TTS_APP_ID=...
#   DOUBAO_TTS_ACCESS_KEY=...
#   DOUBAO_RTASR_API_KEY=...  （可选，不配时 ASR 走本地 whisper）
```

不配置 `.env` 时，语音对话的文本后端可用但不会发声。

## 启动

### 一键启动（Windows）

```
llmcoking\start_all_windows.bat
```

### 手动启动（分别开 3 个终端）

```bash
conda activate deepcoke

# 终端 1 — 文本后端
cd llmcoking/src/LLM_back
python -m uvicorn test:app --host 0.0.0.0 --port 8000

# 终端 2 — 语音后端
cd llmcoking/voice_agent_backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# 终端 3 — 前端
cd llmcoking
npm run serve
```

## 访问

| 入口 | 地址 |
|------|------|
| 前端 | http://localhost:8080 |
| 文本 API 文档 | http://localhost:8000/docs |
| 语音 WS | ws://localhost:8001/ws/duplex |

首次使用需在登录页注册账号（`/register`），之后用此账号登入主界面。

## 目录结构

```
llmcoking/
├── src/
│   ├── LLM_back/              # FastAPI 文本后端
│   │   ├── test.py            # 入口（路由定义）
│   │   └── deepcoke/
│   │       ├── pipeline_graph.py   # LangGraph StateGraph（主 pipeline）
│   │       ├── supervisor.py       # LLM Supervisor 路由
│   │       ├── pipeline.py         # 旧版 if/else pipeline（备用）
│   │       ├── coal_agent/         # 配煤优化 Agent（tools）
│   │       ├── classifier/         # 快速分类 + query 翻译
│   │       ├── vectorstore/        # ChromaDB RAG
│   │       ├── knowledge_graph/    # Neo4j 知识图谱（可选）
│   │       ├── reasoning/          # ESCARGOT 因果推理（可选）
│   │       ├── generation/         # 生成层
│   │       └── followup/           # 追问生成
│   ├── components/            # Vue 2 组件
│   │   ├── MainDia.vue        # 主聊天页
│   │   ├── VoiceAgent.vue     # 语音对话页
│   │   └── ...
│   └── router/
└── voice_agent_backend/       # FastAPI 语音后端（WS 全双工）
    └── app/
        ├── services/
        │   ├── vad_service.py    # Silero VAD
        │   ├── asr_service.py    # Whisper / 豆包 RTASR
        │   └── tts_service.py    # 豆包 TTS / Spark-TTS
        └── routers/duplex_ws.py  # WS 主端点 /ws/duplex
```

## 常见问题

**Q: 点击语音对话没有听到欢迎语?**
A: 检查 `.env` 的豆包 TTS 三件套（APP_ID/ACCESS_KEY/ENCODING）是否配置。不配置时后端 TTS 返回 None，前端只有字幕无声音。浏览器 autoplay 策略首次可能拦截，点击页面任意位置一次即可。

**Q: 文本问答走 Supervisor 路由，日志里怎么看?**
A: 文本后端终端里会看到类似 `deepcoke.supervisor` 的日志行，打印 LLM 决策的 JSON `{"agents": [...], "reasoning": "..."}`。快速通道（关键词匹配）命中时不会调用 LLM。

**Q: chromadb 数据很大，不想下载怎么办?**
A: 不下载时 `knowledge_qa` 路径会报"检索结果为空"，其他 Agent 不受影响。

## 许可

MIT License.
