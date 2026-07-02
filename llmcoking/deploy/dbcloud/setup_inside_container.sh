#!/bin/bash
# 在 dbcloud 容器内跑：装环境 + 起所有服务
# 用法（容器内）: cd /opt/deepcoke/code && bash setup_inside_container.sh [step]
#   step: env | data | services | all（默认 all）
#
# 设计：
# - 分步执行，每步幂等
# - 用 tmux 跑长任务（vLLM 模型加载、抽取脚本）
# - frpc 主动连腾讯云，自动维持隧道

set -e
set -o pipefail

STEP="${1:-all}"
DEEPCOKE_DIR="/opt/deepcoke/code"
DATA_DIR="/opt/deepcoke/data"
MODELS_DIR="/opt/deepcoke/models"
LOG_DIR="/var/log/deepcoke"
FRP_DIR="/opt/frp"
FRP_VERSION="0.59.0"

mkdir -p "$LOG_DIR" "$FRP_DIR"

# ═════════════════════════════════════════════════════════════
echo ""
echo "╔════════════════════════════════════════════╗"
echo "║  DeepCoke 容器内安装 step=$STEP            ║"
echo "╚════════════════════════════════════════════╝"

# 检查我们在容器里（防止误跑在物理机）
if [ "$(hostname)" = "dbcloud" ]; then
    echo "[!] 看起来你在 dbcloud 物理机，这个脚本只能在容器内跑"
    echo "    先：docker exec -it ins_liuhaodong_deepcoke bash"
    exit 1
fi

# ─────────────────────────────────────────────────────────────
if [ "$STEP" = "env" ] || [ "$STEP" = "all" ]; then
    echo ""
    echo "▶ A. 系统包"
    apt-get update -qq
    apt-get install -y -qq \
        vim curl wget git tmux htop \
        mysql-server \
        default-jre-headless \
        build-essential \
        ca-certificates

    echo ""
    echo "▶ B. 装 frp v$FRP_VERSION"
    if [ ! -x "${FRP_DIR}/frpc" ]; then
        cd /tmp
        wget -q "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz" -O frp.tgz \
            || wget -q "https://mirrors.tuna.tsinghua.edu.cn/github-release/fatedier/frp/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz" -O frp.tgz
        tar xzf frp.tgz
        mv frp_${FRP_VERSION}_linux_amd64/* ${FRP_DIR}/
        rm -rf frp_${FRP_VERSION}_linux_amd64 frp.tgz
        chmod +x ${FRP_DIR}/frpc
    fi

    echo ""
    echo "▶ C. Python 依赖（DeepCoke + vLLM）"
    cd "$DEEPCOKE_DIR"
    # 假设代码已经在 /opt/deepcoke/code 下（rsync 进来）
    if [ -f requirements.txt ]; then
        pip install -q -r requirements.txt
    fi
    # vLLM（>= 0.6 支持 Qwen3 系列）
    pip install -q vllm
    pip install -q sshpass 2>/dev/null || true

    echo ""
    echo "▶ D. Neo4j（如果要用知识图谱）"
    if [ ! -d /opt/neo4j ]; then
        cd /tmp
        wget -q https://neo4j.com/artifact.php?name=neo4j-community-5.21.0-unix.tar.gz -O neo4j.tgz
        tar xzf neo4j.tgz -C /opt
        mv /opt/neo4j-community-5.21.0 /opt/neo4j
        rm neo4j.tgz
    fi

    echo "  环境安装完成"
fi

# ─────────────────────────────────────────────────────────────
if [ "$STEP" = "data" ] || [ "$STEP" = "all" ]; then
    echo ""
    echo "▶ E. MySQL"
    if ! pgrep -x mysqld >/dev/null; then
        # MySQL 数据放挂载点 /opt/deepcoke/data/mysql
        mkdir -p /opt/deepcoke/data/mysql
        chown -R mysql:mysql /opt/deepcoke/data/mysql
        # 第一次初始化（如果空）
        if [ -z "$(ls -A /opt/deepcoke/data/mysql 2>/dev/null)" ]; then
            mysqld --initialize-insecure --datadir=/opt/deepcoke/data/mysql
        fi
        nohup mysqld --datadir=/opt/deepcoke/data/mysql --port=3306 \
            > ${LOG_DIR}/mysql.log 2>&1 &
        sleep 5
    fi
    # 建 chat_db + 设密码（如未设）
    mysql -uroot --skip-password -e "
        CREATE DATABASE IF NOT EXISTS chat_db CHARACTER SET utf8mb4;
        ALTER USER 'root'@'localhost' IDENTIFIED BY '123456';
        FLUSH PRIVILEGES;
    " 2>/dev/null || true
    echo "  MySQL OK at 127.0.0.1:3306 / chat_db / root:123456"

    echo ""
    echo "▶ F. Neo4j"
    if ! pgrep -f neo4j >/dev/null; then
        # 数据目录挂载点
        /opt/neo4j/bin/neo4j-admin server set-default-database neo4j 2>/dev/null || true
        nohup /opt/neo4j/bin/neo4j console > ${LOG_DIR}/neo4j.log 2>&1 &
        sleep 8
    fi
    echo "  Neo4j started at bolt://127.0.0.1:7687"

    echo "  数据目录在 /opt/deepcoke/data/{mysql,neo4j,chromadb}"
    echo "  注意：第一次部署需要从开发机 rsync ChromaDB 数据到 data/chromadb/"
fi

# ─────────────────────────────────────────────────────────────
if [ "$STEP" = "services" ] || [ "$STEP" = "all" ]; then
    echo ""
    echo "▶ G. 写 frpc 配置"
    cat > /opt/deepcoke/frpc.toml <<'FRPC_EOF'
serverAddr = "106.52.177.125"
serverPort = 7000

auth.method = "token"
auth.token = "Dc_3jK9pQrL5xN7vM2hY8zT4wU6sE1aB"

log.to = "/var/log/deepcoke/frpc.log"
log.level = "info"
log.maxDays = 7

[[proxies]]
name = "deepcoke-text-backend"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8000
remotePort = 28000

[[proxies]]
name = "deepcoke-voice-backend"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8001
remotePort = 28001
FRPC_EOF

    echo ""
    echo "▶ H. 启服务（tmux 分会话管理）"
    # 容器里没 systemd，用 tmux 跑 4 个服务
    # vLLM + 文本后端 + 语音后端 + frpc

    tmux kill-server 2>/dev/null || true

    # 1) vLLM（Qwen3-32B-AWQ，独占 GPU 0+1 = device-list 在容器内是 0,1）
    tmux new-session -d -s vllm "
        cd /opt/deepcoke
        vllm serve Qwen/Qwen2.5-32B-Instruct-AWQ \
            --tensor-parallel-size 2 \
            --port 11434 \
            --host 127.0.0.1 \
            --max-model-len 32768 \
            --gpu-memory-utilization 0.90 \
            --served-model-name qwen3:8b \
            2>&1 | tee -a $LOG_DIR/vllm.log
    "
    echo "  tmux: vllm 启动（首次拉模型 ~30GB，30 分钟）"

    # 2) 文本后端（先 sleep 等 vLLM）
    tmux new-session -d -s text "
        cd $DEEPCOKE_DIR/src/LLM_back
        sleep 60
        export LLM_MODE=openai
        export AUTH_LEGACY_BYPASS=false
        export DEEPSEEK_BASE_URL=http://127.0.0.1:11434/v1
        export DEEPSEEK_MODEL=qwen3:8b
        export DEEPSEEK_API_KEY=vllm-local
        python -m uvicorn test:app --host 127.0.0.1 --port 8000 \
            2>&1 | tee -a $LOG_DIR/text.log
    "
    echo "  tmux: text-backend 启动（等 vLLM ready 60s 后起）"

    # 3) 语音后端
    if [ -d "$DEEPCOKE_DIR/voice_agent_backend" ]; then
        tmux new-session -d -s voice "
            cd $DEEPCOKE_DIR/voice_agent_backend
            python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 \
                2>&1 | tee -a $LOG_DIR/voice.log
        "
        echo "  tmux: voice-backend 启动"
    fi

    # 4) frpc 隧道
    tmux new-session -d -s frpc "
        /opt/frp/frpc -c /opt/deepcoke/frpc.toml 2>&1 | tee -a $LOG_DIR/frpc.log
    "
    echo "  tmux: frpc 启动（连腾讯云 106.52.177.125:7000）"

    sleep 3
    echo ""
    echo "  tmux 会话列表:"
    tmux ls
fi

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║  ✓ 完成                                      ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "监控:"
echo "  tmux attach -t vllm    # vLLM 启动进度"
echo "  tmux attach -t text    # 文本后端日志"
echo "  tmux attach -t frpc    # 隧道连接日志"
echo "  按 Ctrl+B 然后 D 退出 tmux 但不杀进程"
echo ""
echo "5 分钟后浏览器访问: http://106.52.177.125/"
echo "应该看到 DeepCoke 登录页（vLLM 还在加载就 502，再等等）"
echo ""
