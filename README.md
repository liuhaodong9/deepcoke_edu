# DeepCoke 智能焦化决策平台 — 精简教学版 (edu-lite-langgraph)

焦化配煤智能问答系统。本地部署的多 Agent 对话系统,融合:

- **配煤优化 Agent** — 基于 sklearn + scipy 的焦炭质量 (CRI/CSR/M10/M25) 预测与配方寻优
- **RAG 文献检索** — ChromaDB + BGE embedding,基于焦化领域论文
- **LangGraph Supervisor 路由** — LLM 驱动的声明式多 Agent 图,替代硬编码 if/else
- **全双工语音对话** — Silero VAD + Whisper/豆包 RTASR + DeepSeek + 豆包 TTS,进入即自动朗读欢迎语

本分支 `edu-lite-langgraph` 相对主分支的差异:

- **去掉** 04-07 版的数字孪生视频 UI 和右侧煤仓面板(主聊天页更干净)
- **保留并启用** 04-14 版的 LangGraph + LLM Supervisor 智能路由
- **集成** 豆包 TTS 欢迎语(进语音页即念「您好,我是焦化大语言智能问答与分析系统 DeepCoke……」)

---

## 目录

1. [硬件 / 系统要求](#硬件--系统要求)
2. [前置软件安装](#前置软件安装)
3. [克隆代码](#克隆代码)
4. [Python 环境](#python-环境)
5. [前端依赖](#前端依赖)
6. [MySQL 建库](#mysql-建库)
7. [Ollama 拉取本地 LLM](#ollama-拉取本地-llm)
8. [RAG 向量库数据](#rag-向量库数据)
9. [语音后端配置(可选)](#语音后端配置可选)
10. [启动三个服务](#启动三个服务)
11. [首次使用](#首次使用)
12. [常见问题](#常见问题)
13. [架构](#架构)
14. [目录结构](#目录结构)

---

## 硬件 / 系统要求

| 项 | 最低 | 推荐 |
|---|---|---|
| 操作系统 | Windows 10 / Linux / macOS | **Windows 11**(项目原生) |
| 内存 | 16 GB | 32 GB 以上 |
| GPU | 无(CPU 可用) | NVIDIA RTX,≥ 12 GB 显存(加速 Ollama / Whisper) |
| 磁盘 | 10 GB 可用 | 20 GB 可用 |
| 网络 | 首次安装依赖需外网 | — |

> Linux / macOS 也能跑,但 `start_all_windows.bat` 不可用,需按文末"手动启动"三端开起来。路径分隔符已在代码中使用正斜杠,无兼容问题。

## 前置软件安装

### 1. Anaconda / Miniconda

https://www.anaconda.com/download — 装默认即可。

### 2. Node.js (≥ 16 LTS)

https://nodejs.org/en/download — 装 LTS 版。Windows 装完建议手动加入系统 PATH:

```cmd
set PATH=%PATH%;C:\Program Files\nodejs
```

验证: `node -v` 和 `npm -v` 都返回版本号。

### 3. MySQL 8.0

https://dev.mysql.com/downloads/mysql/ — 下载 MySQL Community Server 8.0。

安装时记住 root 密码。项目默认连接串是 `root:123456@127.0.0.1:3306/chat_db`,如果你的密码不是 `123456`,修改 `llmcoking/src/LLM_back/test.py` 文件顶部的 `DATABASE_URL` 变量。

### 4. Ollama

https://ollama.com/download — 装完双击启动,默认监听 11434 端口。

### 5. Git

https://git-scm.com/download — Windows 自带 Git Bash 很方便。

## 克隆代码

```bash
git clone -b edu-lite-langgraph https://github.com/liuhaodong9/deepcoke_edu.git
cd deepcoke_edu
```

## Python 环境

### 创建 conda 环境

```bash
cd llmcoking
conda env create -f environment.yml
conda activate deepcoke
```

这会创建一个叫 `deepcoke` 的环境,Python 3.11,并用 pip 装好 `environment.yml` 里声明的依赖。

### Windows 系统下的稳定包版本(强烈建议)

直接走默认 pip 会装最新的 torch / cryptography / ctranslate2,它们常因 Windows VC++ Redistributable 版本不匹配而 DLL 加载失败。已验证可跑的稳定组合:

```bash
pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu
pip install "cryptography==42.0.8"
pip install "ctranslate2==4.4.0" "faster-whisper==1.0.3" "setuptools<80"
```

说明:
- 本仓库主 pipeline 的 ML 推理在 CPU 足够快,装 CPU 版 torch 最稳。有 CUDA 12.6 的 GPU 也可换 CUDA 版 torch。
- `cryptography 42` 避免 `_rust` DLL 加载失败(MySQL 认证需要)。
- `ctranslate2 4.4 + faster-whisper 1.0.3 + setuptools<80` 为一组,避开 `pkg_resources` 被 setuptools 82 移除导致的 ImportError。

### 可选: 配煤 Agent 的预训练模型

`coal_agent/` 下的 `*.pkl` (sklearn 1.7.2 训练的焦炭质量预测模型) 已包含在仓库中,直接可用。

## 前端依赖

```bash
# 仍在 deepcoke_edu/llmcoking 目录
npm install
```

如果 npm 从 GitHub 拉某些包很慢,换淘宝镜像:

```bash
npm config set registry https://registry.npmmirror.com
npm install
```

## MySQL 建库

登录 MySQL 后只需建一个空库(表会在后端启动时自动创建):

```sql
CREATE DATABASE IF NOT EXISTS chat_db DEFAULT CHARACTER SET utf8mb4;
```

Windows 命令行:

```cmd
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS chat_db DEFAULT CHARACTER SET utf8mb4;"
```

**如果 root 密码不是 `123456`**,修改 `llmcoking/src/LLM_back/test.py` 顶部(约第 33 行):

```python
DATABASE_URL = "mysql+pymysql://root:你的密码@127.0.0.1:3306/chat_db?charset=utf8mb4"
```

## Ollama 拉取本地 LLM

```bash
ollama pull qwen3:8b
```

模型约 5 GB。只装了 Ollama 没拉模型的话,第一次对话会卡死。可以改用小模型(`ollama pull qwen3:1.7b`),对应修改 `llmcoking/src/LLM_back/deepcoke/config.py` 中的 `OLLAMA_MODEL` 变量。

启动 ollama(若桌面版已自启可跳过):

```bash
ollama serve
```

## RAG 向量库数据

文献 RAG 需要 ChromaDB 向量库。两种方式选一:

### 方式 A: 下载预打包数据(推荐)

Release v1.0 下载 (~46 MB):

- 页面: https://github.com/liuhaodong9/deepcoke_edu/releases/tag/v1.0
- 直链: https://github.com/liuhaodong9/deepcoke_edu/releases/download/v1.0/chromadb_data.tar.gz

解压到 `llmcoking/src/LLM_back/deepcoke/data/chromadb/`:

```bash
# Linux/Mac/Git Bash
mkdir -p llmcoking/src/LLM_back/deepcoke/data
tar -xzf chromadb_data.tar.gz -C llmcoking/src/LLM_back/deepcoke/data

# Windows PowerShell
tar -xzf chromadb_data.tar.gz -C llmcoking/src/LLM_back/deepcoke/data
```

解压后应出现 `data/chromadb/chroma.sqlite3` 等文件。

同时需要 BGE embedding 模型文件放在 `llmcoking/src/LLM_back/deepcoke/data/bge-base-en-v1.5/`。如果没打包可以从 HuggingFace 下载: https://huggingface.co/BAAI/bge-base-en-v1.5 (约 430 MB),或运行:

```bash
cd llmcoking/src/LLM_back
python download_bge.py
```

### 方式 B: 从 PDF 自行摄入

把 PDF 放到 `llmcoking/src/LLM_back/papers/` (自建目录),然后:

```bash
cd llmcoking/src/LLM_back
python fast_ingest.py
```

摄入耗时较长(每篇论文 10-60 秒),会自动用 BGE 向量化并写入 ChromaDB。

### 不配 RAG 数据?

RAG 数据缺失不影响其他 Agent。Supervisor 路由到 `knowledge_qa` 的问题会返回"检索结果为空"。文本问答的其他类别(闲聊/配煤/煤价等)都能正常工作。

## 语音后端配置(可选)

语音对话的高品质 ASR (豆包 RTASR) 和 TTS (豆包) 依赖 API 密钥。**不配置**:

- 语音页仍可打开,但进入时不会听到欢迎语(后端 TTS 返回 None)
- ASR 走本地 Whisper(CPU 跑 `small` 模型,首次用会从 HuggingFace 下载约 460 MB 模型)

### 申请 API

- **豆包 TTS + RTASR**: https://console.volcengine.com/speech/ 申请后能拿到 APP_ID / ACCESS_KEY
- **DeepSeek**(LLM,语音页用,可替换为 Ollama): https://platform.deepseek.com — 注册即送额度

### 填入 .env

```bash
cd llmcoking/voice_agent_backend
cp .env.example .env
```

编辑 `.env`,至少填这几项:

```ini
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 豆包 TTS (让机器人会说话)
ENABLE_SERVER_TTS=true
TTS_PROVIDER=doubao_tts
DOUBAO_TTS_ENDPOINT=https://openspeech.bytedance.com/api/v1/tts
DOUBAO_TTS_APP_ID=你的APP_ID
DOUBAO_TTS_ACCESS_KEY=你的ACCESS_KEY
DOUBAO_TTS_VOICE_TYPE=BV001_streaming
DOUBAO_TTS_ENCODING=mp3
DOUBAO_TTS_SPEED_RATIO=1.2

# 豆包 RTASR (更好的实时转写, 可选; 不填则自动走 Whisper)
DOUBAO_RTASR_API_KEY=

# VAD 灵敏度
VAD_THRESHOLD=0.5
```

**`.env` 绝对不要提交到 git**(已在 `.gitignore` 排除)。

## 启动三个服务

### 一键启动(Windows)

```cmd
llmcoking\start_all_windows.bat
```

脚本会自动打开 3 个 cmd 窗口,分别跑文本后端 (8000)、语音后端 (8001)、前端 (8080)。

### 手动启动(跨平台)

**终端 1 — 文本后端:**

```bash
conda activate deepcoke
cd llmcoking/src/LLM_back
python -m uvicorn test:app --host 0.0.0.0 --port 8000
```

**终端 2 — 语音后端:**

```bash
conda activate deepcoke
cd llmcoking/voice_agent_backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

**终端 3 — 前端:**

```bash
cd llmcoking
npm run serve
```

三个终端都要保持开着。

## 首次使用

### 1. 验证服务

浏览器依次打开(应都有响应):

| 地址 | 期望 |
|---|---|
| http://localhost:8080 | 登录页 |
| http://localhost:8000/docs | Swagger UI(文本 API) |
| http://localhost:8001/health | `{"status":"ok"}` |

### 2. 注册账号

登录页点"注册",填用户名 + 密码,提交。项目没有邮箱/短信验证,本地库里直接建用户。

登录成功进入主聊天页。

### 3. 测试文本问答(Supervisor 路由)

发几条消息,看文本后端终端日志。正确时会看到 `deepcoke.supervisor` 输出 JSON 路由决策:

```
你好                 → simple_chat
CRI 和 CSR 有什么区别  → knowledge_qa
查下今日煤价          → coal_price
优化一下配煤方案       → optimization
```

### 4. 测试语音对话

左侧导航 → 语音对话(或直接访问 `http://localhost:8080/#/Home/VoiceAgent`)。

进入后应:

- 字幕区出现「您好!我是焦化大语言智能问答与分析系统 DeepCoke,有什么可以帮助你的?」
- 豆包女声朗读这句话(需要 `.env` 里配好豆包 TTS)
- 点击"开始通话",浏览器弹出麦克风授权,授权后可对话

> 浏览器 autoplay 策略第一次可能拦音频。如果只看到字幕没听到声音,点页面任意位置一次、或按"开始通话",即可触发播放。

## 常见问题

**Q: `ModuleNotFoundError: No module named 'langgraph'`**
A: 没跑 `pip install -r requirements.txt`。激活 conda 环境后执行。

**Q: MySQL 登录报 `cryptography package is required for sha256_password`**
A: 装 `cryptography==42.0.8`(见上文稳定版本清单)。MySQL 8 默认 `caching_sha2_password` 认证需要这个包,且太新的 cryptography 46+ 在 Windows 上会 DLL 加载失败。

**Q: torch 报 `OSError: [WinError 126] 找不到指定的模块` 指向 `torch_python.dll`**
A: 装了 CUDA 版 torch 但机器 CUDA runtime DLL 缺失。换 CPU 版:
```bash
pip uninstall torch torchaudio -y
pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu
```

**Q: `ImportError: DLL load failed while importing _core`(ctranslate2)**
A: 装 `ctranslate2==4.4.0 faster-whisper==1.0.3 "setuptools<80"`。

**Q: 前端 `localhost refused to connect`**
A: webpack 编译需要 1-3 分钟,等终端 3 出现 `App running at: http://localhost:8080/` 再访问。Vue CLI 热更新慢正常。

**Q: 端口被占用**
A: 改 uvicorn 命令里的 `--port`,同时改前端 `src/main.js` 里的 axios `baseURL` 和 `src/components/VoiceAgent.vue` 里 WS 的端口。

**Q: Ollama 第一次推理很慢**
A: 首次会把模型从磁盘加载到显存/内存,10-30 秒。后续请求会快。

**Q: 首次 Whisper 下载模型卡住**
A: `small` 模型约 460 MB,国内访问 HuggingFace 慢。两个方案:
  1. 改小模型: `.env` 里 `WHISPER_MODEL_SIZE=tiny`(约 40 MB)
  2. 走镜像: 启动语音后端前 `set HF_ENDPOINT=https://hf-mirror.com`

**Q: 进语音页没听到欢迎语**
A: 按顺序排查:
  1. F12 Console 有没有红色报错
  2. 终端 2 (语音后端) 日志里有没有 `greeting failed` 一行
  3. `.env` 的 `DOUBAO_TTS_APP_ID` / `ACCESS_KEY` 是否填了
  4. 点一下页面任意位置,绕过浏览器 autoplay 限制

## 架构

```
┌────────────────────────────────────────────────────────────────┐
│                        Vue 2 前端 (8080)                        │
│   LandingPage → LoginPage → MainDia (chat) / VoiceAgent        │
└──────────┬──────────────────────────────────┬──────────────────┘
           │ HTTP (axios)                     │ WebSocket
           ▼                                  ▼
┌─────────────────────────┐      ┌─────────────────────────────┐
│  文本后端 FastAPI (8000) │      │  语音后端 FastAPI (8001)     │
│                          │      │                              │
│  test.py                 │      │  /ws/duplex                  │
│    └─> process_question  │      │    Silero VAD → ASR → LLM   │
│         (LangGraph graph)│      │    → 豆包 TTS → audio chunks│
└──────────┬───────────────┘      └──────────┬──────────────────┘
           │                                  │
           ▼                                  ▼
┌─────────────────────────┐      ┌─────────────────────────────┐
│  LangGraph StateGraph   │      │  豆包 API / DeepSeek / etc. │
│                          │      └─────────────────────────────┘
│  Supervisor LLM (路由决策)│
│    ├── coal_price        │◄──┐
│    ├── oven_control      │   │  Tools:
│    ├── optimization      │   │  - coal_agent (ML pkl)
│    ├── data_management   │   │  - vectorstore (ChromaDB+BGE)
│    ├── knowledge_qa (RAG)│   │  - knowledge_graph (Neo4j*)
│    └── simple_chat       │   │  - reasoning (ESCARGOT*)
│                          │   │  - Ollama (qwen3:8b)
└──────────────────────────┘   └─  *可选
```

## 目录结构

```
deepcoke_edu/
├── README.md               ← 本文档
├── llmcoking/
│   ├── environment.yml     ← conda 环境定义
│   ├── requirements.txt    ← pip 依赖
│   ├── package.json        ← 前端依赖
│   ├── start_all_windows.bat ← 一键启动
│   ├── src/
│   │   ├── LLM_back/        # Python 文本后端
│   │   │   ├── test.py      ← FastAPI 入口
│   │   │   ├── fast_ingest.py ← PDF 摄入脚本
│   │   │   ├── download_bge.py ← BGE 模型下载
│   │   │   └── deepcoke/
│   │   │       ├── pipeline_graph.py ← LangGraph StateGraph (主 pipeline)
│   │   │       ├── supervisor.py     ← LLM Supervisor 路由
│   │   │       ├── pipeline.py       ← 旧版 if/else pipeline (备用)
│   │   │       ├── llm_client.py     ← Ollama 原生 API 调用
│   │   │       ├── config.py         ← LLM/DB 配置
│   │   │       ├── coal_agent/       ← 配煤优化 (blend_optimizer, quality_predictor, coal_db)
│   │   │       ├── classifier/       ← 快速关键词分类 + query 翻译
│   │   │       ├── vectorstore/      ← ChromaDB RAG 检索
│   │   │       ├── knowledge_graph/  ← Neo4j (可选)
│   │   │       ├── reasoning/        ← ESCARGOT 因果推理 (可选)
│   │   │       ├── generation/       ← 回答生成层
│   │   │       ├── followup/         ← 追问生成
│   │   │       └── data/             ← [gitignore] chromadb + BGE 模型 + papers.db
│   │   ├── components/      # Vue 2 组件
│   │   │   ├── LoginPage.vue
│   │   │   ├── LandingPage.vue
│   │   │   ├── HomePage.vue
│   │   │   ├── MainDia.vue        ← 主聊天页
│   │   │   ├── VoiceAgent.vue     ← 语音对话页
│   │   │   └── SimpleVoice.vue
│   │   ├── router/          # Vue Router
│   │   ├── plugins/
│   │   └── main.js
│   └── voice_agent_backend/ # Python 语音后端
│       ├── pyproject.toml
│       └── app/
│           ├── main.py
│           ├── core/config.py       ← 读 .env
│           ├── routers/duplex_ws.py ← WS 主端点 /ws/duplex
│           └── services/
│               ├── vad_service.py   ← Silero VAD
│               ├── asr_service.py   ← Whisper / 豆包 RTASR
│               ├── tts_service.py   ← 豆包 TTS / Spark-TTS
│               └── deepseek_service.py
└── .gitignore
```

## 许可

MIT License.

## 引用 / 联系

如果你在学术工作里用到了这个项目,感谢引用或提 Issue。仓库: https://github.com/liuhaodong9/deepcoke_edu
