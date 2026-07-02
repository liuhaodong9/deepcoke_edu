# DeepCoke 教育版 — Linux 服务器部署指南

目标服务器: `1.116.164.66`（4×3090 16GB + 128GB RAM + 固定公网 IP）
用户: `dbcloud`

按本指南走完，整套 DeepCoke 在公网可用，需登录后才能调任何 API。

---

## 0. 部署架构

```
公网请求 → nginx :80
            ├── /  → /var/www/deepcoke/dist  （前端 SPA 静态文件）
            ├── /chat /folders ... → 127.0.0.1:8000  （文本后端）
            ├── /papers/X/pdf      → 127.0.0.1:8000  （PDF 文件，鉴权豁免）
            └── /voice/            → 127.0.0.1:8001  （语音后端 WebSocket）

文本后端 8000 → 内部调用 →
   ├── vLLM 11434                 （Qwen3-72B-Int4，4 卡 TP）
   ├── MySQL 3306                  （会话 + 用户表）
   ├── Neo4j 7687                  （知识图谱）
   └── ChromaDB 文件               （文献向量库）

公网防火墙: 仅放行 80/443。8000/8001/11434/3306/7687 一律不出公网。
```

---

## 1. 准备服务器环境（一次性）

### 1.1 系统依赖

```bash
sudo apt update
sudo apt install -y nginx mysql-server git curl build-essential
# Node.js 20（前端构建用）
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 验证 GPU 可见
nvidia-smi
```

### 1.2 Conda + 主环境 `deepcoke`

```bash
# 安装 Miniconda（如未装）
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p $HOME/anaconda3
source $HOME/anaconda3/bin/activate

# 项目主环境（运行后端）
conda create -n deepcoke python=3.10 -y
conda activate deepcoke
cd ~/deepcoke_edu/llmcoking
pip install -r requirements.txt
```

### 1.3 vLLM 单独环境

vLLM 对 PyTorch/CUDA 版本严格，不要跟主环境混。

```bash
conda create -n vllm python=3.11 -y
conda activate vllm
pip install vllm  # 自动拉对应版本 torch
# 验证
vllm --version
```

### 1.4 Neo4j

```bash
# 走 Neo4j 官方 apt repo
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com stable 5' | sudo tee -a /etc/apt/sources.list.d/neo4j.list
sudo apt update && sudo apt install -y neo4j
# 改默认密码（cypher-shell 第一次连接时会提示）
sudo systemctl enable --now neo4j
cypher-shell -u neo4j -p neo4j
# 在 cypher-shell 里执行: CALL dbms.changePassword('你的强密码');
```

---

## 2. 拷贝项目 + 配置

### 2.1 推代码到服务器

本地（Windows）执行：

```powershell
# 用 ssh + rsync（Windows 装 Git Bash 自带 ssh + WSL 的 rsync 或安装 cwRsync）
rsync -avz --exclude node_modules --exclude __pycache__ \
    --exclude '*.pyc' --exclude 'data/chromadb' --exclude 'dist' \
    /d/deepcoke/deepcoke_edu/  dbcloud@1.116.164.66:/home/dbcloud/deepcoke_edu/

# ChromaDB 数据单独传（很大）
rsync -avz /d/deepcoke/deepcoke_edu/llmcoking/src/LLM_back/deepcoke/data/chromadb/ \
    dbcloud@1.116.164.66:/home/dbcloud/deepcoke_edu/llmcoking/src/LLM_back/deepcoke/data/chromadb/
```

或者用 git clone（如果是私有仓）。

### 2.2 配置 `deploy/deepcoke.env`

```bash
ssh dbcloud@1.116.164.66
cd ~/deepcoke_edu/llmcoking/deploy
cp deepcoke.env.example deepcoke.env
chmod 600 deepcoke.env
nano deepcoke.env
# 关键改动：
#   - DATABASE_URL 改 MySQL 强密码
#   - NEO4J_PASSWORD 改强密码
#   - AUTH_LEGACY_BYPASS=false  （生产必须 false）
#   - DEEPSEEK_BASE_URL 不动（默认 http://127.0.0.1:11434/v1）
```

### 2.3 MySQL 配置

```bash
sudo mysql
# 在 mysql 里:
CREATE DATABASE chat_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'deepcoke'@'localhost' IDENTIFIED BY '你的强密码';
GRANT ALL ON chat_db.* TO 'deepcoke'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# 仅监听 127.0.0.1（默认就是，确认一下）
sudo grep bind-address /etc/mysql/mysql.conf.d/mysqld.cnf
```

### 2.4 数据迁移

本地（Windows）执行：

```powershell
# MySQL 数据
mysqldump -h 127.0.0.1 -u root -p123456 chat_db > chat_db.sql
scp chat_db.sql dbcloud@1.116.164.66:/tmp/

# 服务器上导入
ssh dbcloud@1.116.164.66 'mysql -u deepcoke -p chat_db < /tmp/chat_db.sql'

# Neo4j 数据（如果本机有内容）
# 本机停 Neo4j 后 dump:
# neo4j-admin database dump neo4j --to-path=./neo4j-dump
# scp 后服务器 neo4j-admin database load
```

---

## 3. 构建前端

```bash
ssh dbcloud@1.116.164.66
cd ~/deepcoke_edu/llmcoking
npm ci
npm run build
# 产物在 dist/，部署到 nginx 静态目录
sudo mkdir -p /var/www/deepcoke
sudo cp -r dist /var/www/deepcoke/
sudo chown -R www-data:www-data /var/www/deepcoke
```

---

## 4. 配置 nginx

```bash
sudo mkdir -p /var/log/deepcoke /etc/nginx/snippets
sudo cp ~/deepcoke_edu/llmcoking/deploy/nginx.conf /etc/nginx/sites-available/deepcoke
sudo cp ~/deepcoke_edu/llmcoking/deploy/deepcoke_proxy.conf /etc/nginx/snippets/
sudo ln -sf /etc/nginx/sites-available/deepcoke /etc/nginx/sites-enabled/
# 删掉 default
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t  # 检查语法
sudo systemctl reload nginx
```

---

## 5. 起 systemd 服务

```bash
sudo cp ~/deepcoke_edu/llmcoking/deploy/deepcoke-*.service /etc/systemd/system/
sudo mkdir -p /var/log/deepcoke
sudo chown -R dbcloud:dbcloud /var/log/deepcoke

sudo systemctl daemon-reload
# vLLM 先起（首次会下 ~70GB 模型，要等十几分钟）
sudo systemctl enable --now deepcoke-vllm
sudo journalctl -u deepcoke-vllm -f  # 看下载进度，看到 "Uvicorn running" 表示就绪

# 然后起后端
sudo systemctl enable --now deepcoke-text
sudo systemctl enable --now deepcoke-voice

# 状态
sudo systemctl status deepcoke-vllm deepcoke-text deepcoke-voice
```

---

## 6. 防火墙

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS（备用）
sudo ufw enable
sudo ufw status
```

腾讯云控制台的"安全组"也要同步放 80（默认只放 22）。

---

## 7. 抽取数据（B2 离线任务，部署完后执行）

```bash
cd ~/deepcoke_edu/llmcoking/src/LLM_back
conda activate deepcoke
export LLM_MODE=openai  # 走 vLLM

# 先抽 5 篇验证
python -X utf8 -m deepcoke.literature_qa.extract_quant_table --all --limit 5

# 看 papers.db 里抽出来什么
python -c "from deepcoke.literature_qa.quant_schema import get_extraction_stats; print(get_extraction_stats())"

# 抽取质量 OK 后全量
python -X utf8 -m deepcoke.literature_qa.extract_quant_table --all --skip-existing
```

抽完后下次 chat 用户问"挥发分 28-32% 的炼焦煤 CSR"会自动命中字典，前端出 `📊 结构化字典命中` 展开块。

---

## 8. 验证清单

```bash
# 1. 公网能访问前端
curl http://1.116.164.66/  | head -5  # 应返回 SPA index.html

# 2. /login 公开（应 200）
curl -X POST -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"123456"}' \
     http://1.116.164.66/login

# 3. /chat 无 token 应 401
curl -X POST "http://1.116.164.66/chat/?session_id=x&user_message=hi" -i | head -3

# 4. 拿 token 后能调
TOKEN=$(curl -sS -X POST -H "Content-Type: application/json" \
        -d '{"username":"admin","password":"YOURNEWPWD"}' \
        http://1.116.164.66/login | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
curl http://1.116.164.66/folders/?user_id=admin -H "Authorization: Bearer $TOKEN"
```

---

## 9. 上线后必做（安全）

- [ ] 改 `admin` 默认密码（`123456` 必须改）
- [ ] `deepcoke.env` 设 `AUTH_LEGACY_BYPASS=false`
- [ ] MySQL `deepcoke` 用户改强密码
- [ ] Neo4j 密码改（不能继续是 `deepcoke2024`，那是公开在 git 里的）
- [ ] 给 admin 加 SSH pubkey，关掉 ssh 密码登录：`/etc/ssh/sshd_config` 设 `PasswordAuthentication no`
- [ ] 域名 + Let's Encrypt（如果有域名）：
  ```bash
  sudo apt install -y certbot python3-certbot-nginx
  sudo certbot --nginx -d your-domain.com
  ```

---

## 10. 常见故障

| 症状 | 排查 |
|---|---|
| 前端能开但 chat 报 401 | `deepcoke.env` 里 `AUTH_LEGACY_BYPASS` 已设 false，前端 sessionStorage 里 token 是旧的固定字符串。F12 清 localStorage/sessionStorage 重新登录 |
| vLLM 起不来 / OOM | 看 `journalctl -u deepcoke-vllm`：可能 `--gpu-memory-utilization` 太高，调到 0.85；或换更小模型 `Qwen/Qwen2.5-32B-Instruct-AWQ` + `--tensor-parallel-size 2` |
| 流式回答前端卡住 | nginx 没加 `proxy_buffering off`；检查 `/etc/nginx/snippets/deepcoke_proxy.conf` |
| 抽取脚本极慢 | `LLM_MODE=openai` 没设；或 vLLM 没起 |
| `chunk` 不在向量库 | ChromaDB 没传完整。`du -sh data/chromadb/`（本机几百 MB） |

---

## 11. 模型选择参考

4×3090 16GB（共 64GB VRAM）能稳定跑：

| 模型 | 量化 | VRAM | TP | 备注 |
|---|---|---|---|---|
| `Qwen/Qwen2.5-72B-Instruct-AWQ` | AWQ Int4 | ~35GB | 4 | 推荐默认，中文最强 |
| `Qwen/Qwen2.5-32B-Instruct-AWQ` | AWQ Int4 | ~17GB | 2 | 速度更快，质量略降 |
| `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` | FP16 | ~64GB | 4 | 推理强（长思考），但需要全部 VRAM |
| `Qwen/Qwen3-72B-Instruct-AWQ` | AWQ Int4 | ~35GB | 4 | 如 HuggingFace 已发布 Int4 版本 |

抽取定量数据用 Qwen2.5-72B-Instruct-AWQ；NL→SQL 翻译用 Qwen2.5-32B-Instruct-AWQ 已经够。
