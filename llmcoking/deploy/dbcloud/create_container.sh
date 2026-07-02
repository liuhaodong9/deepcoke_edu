#!/bin/bash
# 在 dbcloud 物理机 root shell 跑：起 liuhaodong 专属容器跑 DeepCoke
# 用法: ssh -i 85_rsa root@172.16.110.85 后 bash create_container.sh
#
# 设计：
# - GPU: 独占 0 和 3（已确认空闲）
# - 数据持久化：dbcloud 物理机的 /home/liuhaodong/ 挂进容器 /data
# - 不暴露任何端口给物理机外面（frpc 主动出站，不需要 -p）
# - 镜像复用 nvcr.io/nvidia/pytorch:24.04-py3（如已有则不再拉，省时省盘）
# - 容器名: ins_liuhaodong_deepcoke

set -e

CONTAINER_NAME="ins_liuhaodong_deepcoke"
HOST_DATA_DIR="/home/liuhaodong"

# 智能选镜像：优先复用 dbcloud 上已存在的 nvcr.io/nvidia/pytorch 镜像
# （避免重拉 12GB），都没有再去 nvcr.io 拉新版
EXISTING_PYTORCH=$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
    | grep '^nvcr.io/nvidia/pytorch:' | head -1)
if [ -n "$EXISTING_PYTORCH" ]; then
    IMAGE="$EXISTING_PYTORCH"
    REUSED_IMAGE=true
else
    IMAGE="nvcr.io/nvidia/pytorch:24.04-py3"
    REUSED_IMAGE=false
fi

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║  在 dbcloud 物理机起 DeepCoke 后端容器       ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# ── 1. 安全检查 ──────────────────────────────────────────────
echo "▶ 1/5 安全检查"
if [ "$(hostname)" != "dbcloud" ]; then
    echo "[!] 当前不在 dbcloud 物理机（hostname=$(hostname)），拒绝执行"
    exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "[!] 必须 root 运行"; exit 1
fi

# 容器已存在则提示
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    echo "[i] 容器 $CONTAINER_NAME 已存在"
    echo "    要删除重建？ Ctrl+C 取消，回车继续删除重建"
    read
    docker rm -f "$CONTAINER_NAME"
fi

# ── 2. 准备物理机数据目录 ─────────────────────────────────────
echo ""
echo "▶ 2/5 准备物理机数据目录 $HOST_DATA_DIR"
mkdir -p "$HOST_DATA_DIR"/{code,data,models,logs,configs}
mkdir -p "$HOST_DATA_DIR"/data/{mysql,neo4j,chromadb,hf-cache}
chown -R 1000:1000 "$HOST_DATA_DIR" 2>/dev/null || true
echo "  目录: $HOST_DATA_DIR/{code,data,models,logs,configs}"

# ── 3. 镜像 ──────────────────────────────────────────────────
echo ""
echo "▶ 3/5 镜像 $IMAGE"
if [ "$REUSED_IMAGE" = "true" ]; then
    echo "  复用 dbcloud 上已有镜像 (省 12GB 拉取)"
else
    echo "  本机没有 nvcr.io/nvidia/pytorch 镜像，从 nvcr.io 拉取（约 12GB，~30 分钟）..."
    docker pull "$IMAGE"
fi

# ── 4. 启容器 ────────────────────────────────────────────────
echo ""
echo "▶ 4/5 启动容器 $CONTAINER_NAME"
docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --gpus '"device=0,3"' \
    --ipc=host \
    --ulimit memlock=-1 \
    --ulimit stack=67108864 \
    --shm-size=16g \
    --network bridge \
    -v "$HOST_DATA_DIR/code:/opt/deepcoke/code" \
    -v "$HOST_DATA_DIR/data:/opt/deepcoke/data" \
    -v "$HOST_DATA_DIR/models:/opt/deepcoke/models" \
    -v "$HOST_DATA_DIR/logs:/var/log/deepcoke" \
    -v "$HOST_DATA_DIR/configs:/opt/deepcoke/configs" \
    -e DEEPCOKE_HOST="dbcloud" \
    -e HF_ENDPOINT="https://hf-mirror.com" \
    -e HF_HOME="/opt/deepcoke/models" \
    "$IMAGE" \
    tail -f /dev/null

sleep 2

# ── 5. 验证 ──────────────────────────────────────────────────
echo ""
echo "▶ 5/5 验证"
echo "  容器状态: $(docker inspect -f '{{.State.Status}}' $CONTAINER_NAME)"
echo "  容器 IP:  $(docker inspect -f '{{.NetworkSettings.IPAddress}}' $CONTAINER_NAME)"
echo "  GPU 透传: $(docker exec $CONTAINER_NAME nvidia-smi --query-gpu=index,name --format=csv,noheader 2>&1 | head -4)"

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║  ✓ 容器已起                                  ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "下一步：进容器跑 setup_inside_container.sh"
echo ""
echo "  docker exec -it $CONTAINER_NAME bash"
echo ""
echo "进容器后："
echo "  cd /opt/deepcoke/code  # 代码挂载点"
echo "  bash setup_inside_container.sh"
echo ""
echo "数据目录在物理机 $HOST_DATA_DIR/，容器内为 /opt/deepcoke/{code,data,models,configs}"
echo "持久化：删容器不丢数据，重启容器自动挂回"
echo ""
