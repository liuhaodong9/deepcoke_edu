# DeepCoke 智能焦化决策平台

焦化配煤智能问答系统，支持配煤优化、文献检索和语音对话。

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | >= 3.10 | 后端 |
| Node.js | >= 14 | 前端 |
| MySQL | 8.0 | 会话存储 |
| Ollama | latest | 本地大模型 |

## 安装

```bash
# 前端
npm install

# 后端
pip install -r requirements.txt
```

## 配置

**1. MySQL**

```sql
CREATE DATABASE IF NOT EXISTS chat_db DEFAULT CHARACTER SET utf8mb4;
```

默认连接：`root:123456@127.0.0.1:3306/chat_db`

**2. Ollama 模型**

```bash
ollama pull qwen3:8b
```

## 启动

### 一键启动（Windows）

双击 `start_all_windows.bat`

### 手动启动

```bash
# 终端1 - 后端 (port 8000)
cd src/LLM_back
python -m uvicorn test:app --host 0.0.0.0 --port 8000

# 终端2 - 语音后端 (port 8001，可选)
cd voice_agent_backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# 终端3 - 前端 (port 8080)
npm run serve
```

> Windows 下若 Node.js 未加入 PATH：`$env:Path += ";C:\Program Files\nodejs"`

## 访问

- 前端界面：http://localhost:8080
- 后端 API 文档：http://localhost:8000/docs

## 许可

MIT License
