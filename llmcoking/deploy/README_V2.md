# DeepCoke 教育版部署手册 V2（2026-06-02）

**架构**：腾讯云轻量做公网入口 + dbcloud 物理机做 GPU 后端 + frp 反向隧道

```
公网用户 ──HTTP──> 106.52.177.125:80  (腾讯云 / Ubuntu 22.04 / 2核2G)
                  │
                  ├── nginx 反代 / → /var/www/deepcoke/dist (前端静态)
                  └── nginx 反代 /chat /folders ... → 127.0.0.1:28000 (frps 隧道暴露端口)

[frp 反向隧道：dbcloud 主动出站到腾讯云 7000]

dbcloud 物理机 172.16.110.85 root
  ├── 跑深脑云平台（其他人用，不动）
  └── 我们的 docker 容器 ins_liuhaodong_deepcoke
       ├── vLLM Qwen3-32B-AWQ :11434 (GPU 0+3 独占, ~32GB VRAM)
       ├── DeepCoke 文本后端 :8000 (FastAPI)
       ├── DeepCoke 语音后端 :8001 (FastAPI WebSocket)
       ├── MySQL :3306 (chat_db)
       ├── Neo4j :7687 (知识图谱)
       ├── ChromaDB (8024 chunks 向量库)
       └── frpc 主动连 106.52.177.125:7000，把本地 8000/8001 隧道到腾讯云 28000/28001
```

---

## 阶段 1：腾讯云入口机配置（你已经买好，5 分钟）

### 1.1 在腾讯云控制台开端口
进入实例 → 防火墙 → 加规则：
- TCP **80** 来源 0.0.0.0/0（HTTP 入口）
- TCP **7000** 来源 0.0.0.0/0（frps，dbcloud 隧道接入）

22 默认已开。

### 1.2 SSH 登入腾讯云（用控制台给的密码）
```bash
ssh root@106.52.177.125
```

### 1.3 把本地 `deploy/tencent/install.sh` 传到腾讯云

**最简单**：直接复制粘贴。打开 `D:\deepcoke\deepcoke_edu\llmcoking\deploy\tencent\install.sh`，全选复制；在腾讯云 SSH 里：
```bash
cat > install.sh <<'INSTALL_END'
（粘贴 install.sh 全部内容）
INSTALL_END
chmod +x install.sh
bash install.sh
```

或者从本地 scp（如果你装了 git/scp）：
```bash
scp -r D:\deepcoke\deepcoke_edu\llmcoking\deploy\tencent\* root@106.52.177.125:/root/
ssh root@106.52.177.125
cd /root && bash install.sh
```

### 1.4 验证

腾讯云 SSH 里：
```bash
systemctl status nginx deepcoke-frps
curl http://localhost/  # 看到占位 HTML
```

浏览器打开 `http://106.52.177.125/` 应该看到 **"DeepCoke Gateway 已就绪"** 占位页。

---

## 阶段 2：dbcloud 物理机起容器（10 分钟，含拉镜像）

### 2.1 在 Lab 3 SSH 上 dbcloud 物理机
```cmd
ssh -i D:\85_rsa root@172.16.110.85
```

### 2.2 把 `create_container.sh` 传到 dbcloud（同 1.3 方式）
```bash
cat > /root/create_container.sh <<'CREATE_END'
（粘贴 deploy/dbcloud/create_container.sh 全部内容）
CREATE_END
chmod +x /root/create_container.sh
bash /root/create_container.sh
```

第一次跑会拉 12GB 镜像，~10 分钟。看到 "✓ 容器已起" 表示 OK。

### 2.3 把 DeepCoke 代码传到 dbcloud
**从本地 Windows**（一次性，~50MB 代码 + ~500MB ChromaDB）：
```cmd
:: Lab 3 上跑（或者从你开发机走 VPN）
scp -i D:\85_rsa -r D:\deepcoke\deepcoke_edu\llmcoking\* root@172.16.110.85:/home/liuhaodong/code/
:: ChromaDB 数据
scp -i D:\85_rsa -r D:\deepcoke\deepcoke_edu\llmcoking\src\LLM_back\deepcoke\data\chromadb\* root@172.16.110.85:/home/liuhaodong/data/chromadb/
```

代码就放在物理机 `/home/liuhaodong/code/`，会通过 docker volume 出现在容器内 `/opt/deepcoke/code/`。

---

## 阶段 3：进容器装环境 + 起服务（30-60 分钟）

### 3.1 进容器
```bash
docker exec -it ins_liuhaodong_deepcoke bash
```

### 3.2 跑安装脚本
```bash
cd /opt/deepcoke/code/deploy/dbcloud
bash setup_inside_container.sh all
```

分 3 步可单独跑：
- `setup_inside_container.sh env` — 装 conda 依赖 + frp + vLLM + Neo4j
- `setup_inside_container.sh data` — 起 MySQL + Neo4j
- `setup_inside_container.sh services` — 起 vLLM + 后端 + frpc（用 tmux）

### 3.3 监控启动进度
```bash
# vLLM 模型首次下载，~30 分钟
tmux attach -t vllm
# Ctrl+B D 退出但不杀进程

# 文本后端
tmux attach -t text

# frpc 隧道
tmux attach -t frpc
```

frpc 启动 30 秒内会看到日志里 `start proxy success` 表示隧道通了。

---

## 阶段 4：验证

### 4.1 内部链路
dbcloud 容器内：
```bash
curl http://127.0.0.1:8000/login  # 文本后端 200
curl http://127.0.0.1:11434/v1/models  # vLLM
```

### 4.2 公网链路
浏览器：`http://106.52.177.125/`
- 看到 DeepCoke 登录页（不是占位页了）→ ✅ 公网入口 + 前端就绪
- 用 admin / 123456 登录（**临时密码，立刻改**）
- 跑一个简单问题（"焦炭是什么"）能流式返回 → ✅ 整条链路通

### 4.3 字典抽取（B2，离线任务）
登入容器后：
```bash
docker exec -it ins_liuhaodong_deepcoke bash
cd /opt/deepcoke/code/src/LLM_back
export LLM_MODE=openai
# 先抽 5 篇验证
python -X utf8 -m deepcoke.literature_qa.extract_quant_table --all --limit 5
# 看抽出来的数据
python -c "from deepcoke.literature_qa.quant_schema import get_extraction_stats; print(get_extraction_stats())"
# 质量 OK 后全量
python -X utf8 -m deepcoke.literature_qa.extract_quant_table --all --skip-existing
```

vLLM Qwen3-32B 抽 231 篇大概 1-2 小时。抽完后下次问"挥发分 30% 的炼焦煤 CSR"会自动命中字典。

---

## 阶段 5：上线后必做（安全）

- [ ] 改 `admin` 默认密码 `123456`
- [ ] dbcloud 容器内 `export AUTH_LEGACY_BYPASS=false` 重启 text 后端（关掉 legacy "I have login"）
- [ ] MySQL root 密码改强密码（容器内本地访问，但还是改）
- [ ] Neo4j 密码改（默认 neo4j/deepcoke2024 写死在 git 里）
- [ ] 腾讯云 SSH 加 pubkey、关密码登录
- [ ] frp token 改成你自己的（改两处：腾讯云 frps.toml + dbcloud frpc.toml）

---

## 故障排查

| 症状 | 处理 |
|---|---|
| `http://106.52.177.125/` 502 Bad Gateway | frpc 还没连上腾讯云。看 `tmux attach -t frpc` 日志 |
| vLLM 卡在 "Loading model" | 模型在下，~30 分钟正常。后台 `tmux attach -t vllm` 看进度 |
| 抽取脚本报 timeout | vLLM 还没就绪，等到 `tmux attach -t vllm` 看到 `Uvicorn running on http://127.0.0.1:11434` 再跑 |
| 前端能开但 chat 401 | sessionStorage 里有旧 token，F12 清掉重新登 |
| 腾讯云 ssh 不上 | 控制台重置密码 / 看安全组 22 端口开了没 |
| dbcloud 容器 GPU 用错卡 | 改 create_container.sh 里 `--gpus '"device=0,3"'` 那行 |

---

## 文件清单

```
deploy/
├── README_V2.md             ← 本文档
├── tencent/
│   ├── install.sh           ← 腾讯云一键脚本（含 nginx + frps + systemd）
│   ├── frps.toml            ← frp 服务端配置（参考用，已嵌入 install.sh）
│   ├── nginx_deepcoke.conf  ← nginx 反代配置（参考用，已嵌入 install.sh）
│   └── deepcoke-frps.service ← systemd unit（已嵌入 install.sh）
└── dbcloud/
    ├── create_container.sh  ← 在物理机起 docker 容器
    ├── setup_inside_container.sh ← 容器内装环境+起服务（tmux）
    └── frpc.toml            ← frp 客户端配置（参考用，已嵌入 setup_inside_container.sh）
```
