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
9. [Neo4j 知识图谱](#neo4j-知识图谱)
10. [ESCARGOT 推理](#escargot-推理)
11. [语音后端配置](#语音后端配置)
12. [启动三个服务](#启动三个服务)
13. [首次使用](#首次使用)
14. [常见问题](#常见问题)
15. [架构](#架构)
16. [目录结构](#目录结构)

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

### 装 Silero VAD(必装,否则语音连线会超时崩)

语音后端 `SileroVAD` 找不到 pip 包会回退到 `torch.hub.load("snakers4/silero-vad")`,国内/离线机器访问 GitHub 必超时,客户端连 `/ws/duplex` 时 uvicorn 会报 `WinError 10060`,每连必炸。

```bash
pip install silero-vad
# 校验(打印模型对象即通过)
python -c "from silero_vad import load_silero_vad; load_silero_vad(); print('ok')"
```

最新的 `environment.yml` 已把它列为默认依赖。老环境一条命令同步:
```bash
conda env update -f llmcoking/environment.yml --prune
```

### 配煤 Agent 的预训练模型

`coal_agent/` 下的 `*.pkl` (sklearn 1.7.2 训练的焦炭质量预测模型) 已包含在仓库中,直接可用,无需额外下载。

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

### Pipeline 进度条 HTML 显示成源码的修法

跑起来后,如果主聊天页里 bot 回复出现 `<div class="pipeline-progress">...</div>` 这种**源码标签**而不是渲染成进度条,根因是 `MainDia.vue:128` 的 `renderMarkdown` 在跑 `marked()` 之前**先把 `<` `>` 全部转义成 `&lt;` `&gt;`**(只白名单了 `<details>` `<summary>`)防 XSS,而文本后端的 `pipeline_graph.py` 在流式输出里塞的 `<div class="pipeline-progress">` 自定义 HTML 被一并转义掉了。

修法二选一:

1. **前端**:在 `MainDia.vue:130` 的占位符白名单里加上 `pipeline-progress` 等已知 class 的 `<div>` / `<span>`(参照 `details/summary` 的 `__DETAILS_PH_${idx}__` 处理),或者改成用 DOMPurify 做真正的 sanitize 而不是粗暴转义。
2. **后端**:把 `pipeline_graph.py:_progress_html` 里的 `<div class="pipeline-progress">` 换成等价的 markdown 块(表情符号 + 进度文本),让前端不需要解析 HTML。

博主当前用的是方案 1 的占位符思路,改 `MainDia.vue:130` 的正则即可。改完 `npm run serve` 会热更新,刷新页面验证。

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

文献 RAG 需要 ChromaDB 向量库。从 Release v1.0 下载预打包数据 (~46 MB):

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

### 下载 BGE embedding 模型

向量库要跟 BGE embedding 模型配对使用,放在 `llmcoking/src/LLM_back/deepcoke/data/bge-base-en-v1.5/`(约 430 MB):

```bash
cd llmcoking/src/LLM_back
python download_bge.py
```

该脚本走 ModelScope 拉,国内直连即可,不需要翻墙。

### 召回为 0 (`[retrieve] 0 unique chunks`) 排查

启动后端后第一次问 knowledge_qa 类问题,如果终端日志打 `[retrieve] 0 unique chunks`,意味着向量检索一条都没命中。三种可能,按概率排查:

1. **BGE 模型没下完整**:`ls llmcoking/src/LLM_back/deepcoke/data/bge-base-en-v1.5/` 必须看到 `model.safetensors` / `config.json` / `tokenizer.json` 等。少文件就是 `download_bge.py` 中途断了,重跑一次。
2. **chromadb 数据没解压到位**:`ls llmcoking/src/LLM_back/deepcoke/data/chromadb/` 必须看到 `chroma.sqlite3` 加一个 UUID 子目录(里面有 `data_level0.bin` 等)。少了就回上一节重做 `tar -xzf`。
3. **embedding 维度不匹配**:`vectorstore/chromadb_store.py:59` 在 collection 已存在时**故意不传 `embedding_function`** 来避免冲突,前提是 BGE 在第一次 `download_bge.py` 后能被 SentenceTransformer 自动识别。如果终端打了 `[ChromaDB] SentenceTransformer init failed ... using default embeddings`,说明回退到了 384 维默认 embedding,跟库里 768 维 BGE 向量对不上 → query 全 0 命中。修法:`pip install -U sentence-transformers`,确认 `EMBEDDING_MODEL` 路径(`config.py:19`)指向的目录里 `config.json` 存在,然后**重启后端**清掉 ChromaDB 客户端进程缓存。

## Neo4j 知识图谱

`knowledge_qa` 路线在向量检索后会走一步 `kg_lookup`,从 Neo4j 取关联论文(`pipeline_graph.py:239`)。pipeline 对这一步包了 `try/except` 做兜底 —— Neo4j 连不上时日志会打 `[kg_lookup] non-fatal: ...`,进度条改成"知识图谱:跳过(连接异常)",流程继续跑完打印 `=== COMPLETE ===`。但这种情况下**当次问答实际没有知识图谱补充数据,回答是降级的**,所以一定要把 Neo4j 配好。

### 默认连接参数(`deepcoke/config.py`)

```python
NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "deepcoke2024"
```

支持用 `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` 环境变量覆盖。下面步骤默认你用的就是这组默认值。

### 装 Neo4j 并对齐密码

1. 下载 Neo4j Desktop: https://neo4j.com/download/
2. 启动 Neo4j,首次登录会强制改密码 —— **改成 `deepcoke2024`**(或用其他密码,但启动后端前必须 `set NEO4J_PASSWORD=你的密码`)
3. 浏览器打开 http://localhost:7474 能登录即 OK
4. **先抽实体,再灌图**(顺序不能反,缺第一步整个图就是空的):

   ```bash
   cd llmcoking/src/LLM_back

   # 第 1 步：用本地 Ollama 从 papers.db 里抽实体,产出 kg_entities.json
   python -m deepcoke.knowledge_graph.extract_entities

   # 第 2 步：把 kg_entities.json 灌进 Neo4j
   python -m deepcoke.knowledge_graph.import_entities
   ```

> **为什么要分两步**:`papers.db` 已包含在 chromadb 数据包里(解压后自动到位),但 `kg_entities.json` 不随仓库分发,必须现场用 LLM 抽。第 1 步会调本地 Ollama 几百次(每篇论文一次),qwen3:8b 在 RTX 4090D 上大约 30~60 分钟跑完,中途断了重跑会从断点续抽。
>
> 第 2 步跑完末尾应打印:
> ```
> Graph stats:
>   Concept: 1xxx
>   Paper: 2xx
>   Method: xx
>   ...
> Relationships:
>   STUDIES_CONCEPT: 4xxx
>   ...
> ```
>
> **如果跳过这两步直接启后端**,knowledge_qa 跑到 `kg_lookup` 时 Neo4j 日志会刷一堆告警:
>
> ```
> The relationship type STUDIES_CONCEPT does not exist
> The label Concept does not exist
> The property paper_id does not exist
> ```
>
> 来源是 `neo4j_client.py:51` 那条 `MATCH (p:Paper)-[:STUDIES_CONCEPT]->(c:Concept)` Cypher,空库自然命中不到任何东西。pipeline 包了 `try/except`,所以不会崩,但 `> **知识图谱补充：**` 那一段引用块也不会出现 —— 当次回答完全降级成纯 RAG。

### Neo4j 报错处理

启动后端后第一次 knowledge_qa 问答,如果后端日志出现:

```
Neo.ClientError.Security.Unauthorized — The client is unauthorized due to authentication failure.
...(几次重试后)...
Neo.ClientError.Security.AuthenticationRateLimit — The client has provided incorrect authentication details too many times in a row.
```

意味着:
- `Unauthorized`:密码对不上。回上一步把密码改成 `deepcoke2024`,或给后端设 `NEO4J_PASSWORD` 环境变量对齐。
- `AuthenticationRateLimit`:重试太多次,Neo4j 把客户端暂时拉黑了。**改对密码也不会立刻生效**,必须二选一:
  1. 等 5~30 分钟让限流窗口过期
  2. 重启 Neo4j 清除限流状态
     - Desktop:点停止 → 再点启动
     - Community Server:`neo4j restart`(Linux/Mac)或在服务管理器里重启 Neo4j 服务(Windows)

> **防坑提示**:改完密码或重启 Neo4j 后,**一定要同时重启文本后端**(终端 1 那个 `uvicorn test:app`),否则进程里缓存的 driver 会继续用老密码连,又把自己撞进限流。

## ESCARGOT 推理

`knowledge_qa` 路线在 `kg_lookup` 之后会走 `node_reason`,调 `run_escargot_reasoning`(`pipeline_graph.py:273`)做基于 Graph of Thoughts 的因果推理。`reasoning/escargot_runner.py:14` 用 try/except 包了 `from escargot.controller.controller import Controller`,没装时只会在日志里打:

```
ESCARGOT not available: No module named 'escargot'
```

**流程不会崩,但当次回答里没有「深度推理 (ESCARGOT)」那一段证据,知识图谱回答质量明显降级。**所以这一步必装。

`environment.yml` / `requirements.txt` 故意没把它列成默认依赖 —— ESCARGOT 在 PyPI 上版本(0.0.3)落后于 GitHub 主分支,且要跟仓库里的 `deepseek_lm.py` / `coking_prompter.py` 对齐用法,所以走源码 editable 安装最稳。

### 1. 拉源码到 `D:\escargot`

```bash
git clone https://github.com/EpistasisLab/escargot.git D:/escargot
```

> 项目代码 `deepcoke/config.py:30` 里 `ESCARGOT_DIR` 默认就是 `<项目根>/../escargot`,但博主本地是直接放 `D:\escargot` 并通过 pip editable 安装注册到 site-packages,后者优先级更高,所以路径放哪儿都行,只要下一步 `pip install -e` 装上即可。

### 2. editable 安装

```bash
conda activate deepcoke
pip install -e D:/escargot
```

ESCARGOT 自身依赖里有 `gqlalchemy` / `weaviate-client` / `chromadb` 等十几个包,这一步会顺带把没装上的都补齐(可能要 1-2 分钟)。

### 3. 验证

```bash
python -c "import escargot; from escargot.controller.controller import Controller; print('ok ->', escargot.__file__)"
```

打印 `ok -> D:\escargot\escargot\__init__.py` 即通过。

启动文本后端后,跑一句 knowledge_qa 类问题(如「CRI 和 CSR 有什么区别」),终端日志里如果**没有** `ESCARGOT not available` 那一行,且回答正文里出现 `> **深度推理 (ESCARGOT):**` 引用块,则整条链路工作正常。

## 语音后端配置

语音对话用的是豆包 TTS 合成女声欢迎语、豆包 RTASR 做实时转写、DeepSeek 做对话、本地 Whisper 做 RTASR 降级兜底。下面四步按顺序做完。

### 配置 HuggingFace 镜像

Whisper 首次加载时走 `huggingface_hub.snapshot_download` 拉 `Systran/faster-whisper-small` 模型,国内直连 `huggingface.co` 必超时。不设镜像就跑不起来。典型报错链:

```
httpcore.ConnectTimeout: [WinError 10060] 由于连接方在一段时间后没有正确答复...
  → huggingface_hub.snapshot_download
  → api.repo_info("huggingface.co/...")
```

触发时机:**前端连上 `/ws/duplex` 的那一刻** —— `DuplexSession` 初始化 `ASRService` → `WhisperModel(...)` → HF 下载 → 超时 → WS 握手失败。所以只要没把镜像设好,第一次打开语音页就必炸。

**解决:永久设置 `HF_ENDPOINT` 环境变量,指向镜像。**

Windows (PowerShell,永久生效,需重开所有终端):
```powershell
[Environment]::SetEnvironmentVariable("HF_ENDPOINT", "https://hf-mirror.com", "User")
```

Windows (cmd,当前窗口临时生效,每次启动语音后端前执行):
```cmd
set HF_ENDPOINT=https://hf-mirror.com
```

Linux / macOS:
```bash
echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.bashrc
source ~/.bashrc
```

验证:新开终端执行 `echo %HF_ENDPOINT%`(Windows) 或 `echo $HF_ENDPOINT`(Linux/Mac),打印出镜像地址即 OK。

### 申请 API 密钥

- **豆包 TTS + RTASR**: https://console.volcengine.com/speech/ 申请后能拿到 APP_ID / ACCESS_KEY
- **DeepSeek**: https://platform.deepseek.com — 注册即送额度,用于语音页对话生成

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

# 豆包 RTASR (实时转写)
DOUBAO_RTASR_API_KEY=你的RTASR_KEY

# VAD 灵敏度
VAD_THRESHOLD=0.5
```

**`.env` 绝对不要提交到 git**(已在 `.gitignore` 排除)。

### Whisper 启动报 `Could not locate cudnn_ops_infer64_8.dll`

跑起来后,前端打开语音页,终端 2 先打:

```
WebSocket /ws/duplex [accepted]
connection open
```

紧接着炸:

```
Could not locate cudnn_ops_infer64_8.dll.
Please make sure it is in your library path!
```

WS 一秒断掉,下一次连还是同样的错。

**根因**:`WHISPER_DEVICE` 默认 `auto`(`voice_agent_backend/app/core/config.py:18`),`asr_service.py:36-47` 检测到 `torch.cuda.is_available()` 为 True 就走 CUDA 分支,以 `WhisperModel(..., device="cuda", compute_type="float16")` 初始化 ctranslate2。ctranslate2 的 GPU 后端在 forward 时要去加载 `cudnn_ops_infer64_8.dll` / `cudnn_cnn_infer64_8.dll` 这一组 cuDNN 8.x 推理库,**而 PyTorch 安装时自带的 CUDA runtime 不包含这些 DLL,必须单独装 NVIDIA cuDNN**。机器装了 CUDA 12.x 但没装 cuDNN 8.x 必触发。

修法二选一:

1. **强制 Whisper 走 CPU(推荐,改一行就好)**:`voice_agent_backend/.env` 里加 / 改:
   ```ini
   WHISPER_DEVICE=cpu
   WHISPER_COMPUTE_TYPE=int8
   ```
   项目里 Whisper 只是 RTASR 失败时的离线兜底,默认 `small` 模型 + int8 在 CPU 上 RTF 远小于 1,实时转写完全够用。改完重启语音后端(终端 2)即生效。
2. **装 cuDNN 8.x 让 GPU 路径跑通**:NVIDIA 官网下载与你 CUDA 版本对应的 cuDNN 8.9.x(`https://developer.nvidia.com/cudnn-archive`,需 NVIDIA 账号),把压缩包里 `bin\` 下的 `cudnn_ops_infer64_8.dll` / `cudnn_cnn_infer64_8.dll` / `cudnn_ops_train64_8.dll` / `cudnn_adv_infer64_8.dll` 等几个 DLL 拷到 `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\bin\`(已在 PATH 上),或单开一个目录加进系统 PATH。重启终端 2 验证。注意 cuDNN 9.x **不行**,ctranslate2 4.4 还在用 cuDNN 8.x 的 ABI,装错版本同样报这条错。

### 打断 / 切页面后日志冒一段 CancelledError 的说明

跑起来后,用户在 AI 说话过程中开口打断、或直接关掉浏览器标签时,终端 2 会冒出类似 traceback:

```
asyncio.exceptions.CancelledError
  File "...\deepseek_service.py", line 34, in deepseek_stream_chat
    async with client.stream("POST", url, ...) as resp:
  File "...\duplex_ws.py", line ..., in _runner
    ...
Task was destroyed but it is pending!
task: <Task pending name='Task-NN' coro=<DuplexSession.tts_worker() ...>>
```

**这是正常的清理告警,不是崩溃**。链路:VAD 检测到用户开口 → `_on_vad_speech_start` → `_interrupt`(`duplex_ws.py:516`) → `_cancel_llm`(`duplex_ws.py:537`) → 把当前 LLM Task `cancel()`。LLM Task 此刻正卡在 `httpx` 的 `client.stream("POST", ...)` await 上,于是 `CancelledError` 在 `deepseek_service.py:34` 抛出冒到 `_runner`,被 `except CancelledError: raise` 重抛(`duplex_ws.py:420`),最终被 `_cancel_llm` 里的 `contextlib.suppress(Exception)`(`duplex_ws.py:540`)吞掉。整条 traceback 只是 Python 在打 cancel 路径,不影响下一轮对话。

`Task was destroyed but it is pending!` 同理 —— WebSocket 关闭时 `finally` 块 `tts_task.cancel()`(`duplex_ws.py:653`),偶发 `tts_worker` 正卡在 `await self._tts_q.get()`,Python GC 时还没完成 cancel 就打这条警告。**可忽略**。

想把日志清干净的话:`deepseek_service.py:33` 的 `async with httpx.AsyncClient(...)` 外面再包一层 `try/except asyncio.CancelledError: return`,以及 `duplex_ws.py:651` 的 `finally` 里把三个 task 的 cancel 改成 `await asyncio.gather(*tasks, return_exceptions=True)` 等齐再退出。但这只是降噪,跟实际行为无关。

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
│    ├── knowledge_qa (RAG)│   │  - knowledge_graph (Neo4j)
│    └── simple_chat       │   │  - reasoning (ESCARGOT)
│                          │   │  - Ollama (qwen3:8b)
└──────────────────────────┘   └─
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
│   │   │       ├── knowledge_graph/  ← Neo4j
│   │   │       ├── reasoning/        ← ESCARGOT 因果推理
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
