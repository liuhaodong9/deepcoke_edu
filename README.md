# DeepCoke 智能焦化决策平台

焦化配煤智能问答系统，支持配煤优化、文献检索和语音对话。全本地部署，无需联网。

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Anaconda | latest | Python 环境管理 |
| Node.js | >= 14 | 前端 |
| MySQL | 8.0 | 会话存储 |
| Ollama | latest | 本地大模型 |

## 安装

### 1. 创建 conda 环境

```bash
cd llmcoking
conda env create -f environment.yml
conda activate deepcoke
```

> `environment.yml` 已包含 `silero-vad` pip 包。**一定要确认它安装成功**，否则语音后端会去 GitHub 拉仓库，国内网络会超时报 `WinError 10060`（见下方「常见问题」）。
>
> 校验：
> ```bash
> python -c "from silero_vad import load_silero_vad; print(load_silero_vad())"
> ```
> 正常应打印出模型对象。若报 `ModuleNotFoundError`，手动补装：
> ```bash
> pip install silero-vad
> ```

### 2. 安装前端依赖

```bash
npm install
```

> Windows 下若 Node.js 未加入 PATH：`set PATH=%PATH%;C:\Program Files\nodejs`

### 3. 配置 MySQL

```sql
CREATE DATABASE IF NOT EXISTS chat_db DEFAULT CHARACTER SET utf8mb4;
```

默认连接：`root:123456@127.0.0.1:3306/chat_db`

### 4. 下载 Ollama 模型

```bash
ollama pull qwen3:8b
```

### 5. 文献数据（可选）

从 [Releases](../../releases) 下载 `chromadb_data.tar.gz`，解压到 `llmcoking/src/LLM_back/deepcoke/data/chromadb/`。

## 启动

### 一键启动（Windows）

双击 `llmcoking/start_all_windows.bat`

### 手动启动

先激活环境：

```bash
conda activate deepcoke
cd llmcoking
```

```bash
# 终端1 - 文本后端 (port 8000)
cd src/LLM_back
python -m uvicorn test:app --host 0.0.0.0 --port 8000

# 终端2 - 语音后端 (port 8001)
cd voice_agent_backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# 终端3 - 前端 (port 8080)
npm run serve
```

## 访问

- 前端界面：http://localhost:8080
- 后端 API 文档：http://localhost:8000/docs

## 常见问题

### 语音后端连 `/ws/duplex` 时报 `WinError 10060` / `torch.hub` 拉 GitHub 超时

**现象**：客户端连 `ws://127.0.0.1:8001/ws/duplex` 时，uvicorn 报错链大致为：

```
TimeoutError: [WinError 10060] 由于连接方在一段时间后没有正确答复...
urllib.error.URLError: <urlopen error [WinError 10060] ...>
RuntimeError: It looks like there is no internet connection and the repo could not be found in the cache (C:\Users\<你>\.cache\torch\hub)
  File "app/services/vad_service.py", line 35, in _load
    torch.hub.load(repo_or_dir="snakers4/silero-vad", ...)
  File "app/routers/duplex_ws.py", line 96
ERROR: Exception in ASGI application
```

**根本原因**：`SileroVAD._load()` 优先尝试 `from silero_vad import ...`，失败后回退到 `torch.hub.load("snakers4/silero-vad", ...)`，这一步会访问 `https://github.com/snakers4/silero-vad/tree/main/`。国内主机或离线机器访问 GitHub 超时，就会抛 `WinError 10060`。每一次新的 WebSocket 连接都会触发 `DuplexSession.__init__` → `SileroVAD()` → `_load()`，所以看起来"每次连就炸"。

**解决方法（三选一）**：

1. **推荐：装 `silero-vad` pip 包**（零网络依赖，冷启动最快）

   ```bash
   conda activate deepcoke
   pip install silero-vad
   # 校验
   python -c "from silero_vad import load_silero_vad; load_silero_vad(); print('ok')"
   ```
   `vad_service.py` 检测到这个包后就不会再走 `torch.hub`，彻底绕开 GitHub。

2. **预热 torch.hub 缓存**（保留原逻辑，但提前在能联网的机器上拉一次）

   在能访问 GitHub 的环境里执行一次：
   ```bash
   python -c "import torch; torch.hub.load('snakers4/silero-vad', 'silero_vad', trust_repo=True)"
   ```
   会把仓库缓存到 `C:\Users\<你>\.cache\torch\hub\snakers4_silero-vad_master\`，之后断网也能用。把这个目录复制到目标机器同样路径下即可。

3. **离线机器：手动放置仓库**

   - 下载 <https://github.com/snakers4/silero-vad> 的 master 分支 zip
   - 解压为 `C:\Users\<你>\.cache\torch\hub\snakers4_silero-vad_master\`
   - 确保里面有 `hubconf.py`

### `npm run serve` 找不到 node

Windows 下 Node.js 没进系统 PATH。临时解决：

```bash
set PATH=%PATH%;C:\Program Files\nodejs
```

### Ollama 调用 502

不要用 `openai` Python SDK 调 Ollama。项目统一用 `requests` 调 `/api/chat` 原生接口，见 `src/LLM_back/deepcoke/llm_client.py`。

## 许可

MIT License
