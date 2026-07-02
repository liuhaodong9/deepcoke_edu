#!/bin/bash
# DeepCoke 腾讯云入口机一键安装脚本
# 用法: 以 root 登录 106.52.177.125 后跑 bash install.sh
# 幂等：重复跑也安全（已装的会跳过/覆盖）

set -e
set -o pipefail

FRP_VERSION="0.59.0"
FRP_DIR="/opt/frp"
DEPLOY_DIR="/opt/deepcoke"
LOG_DIR="/var/log/deepcoke"

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║  DeepCoke 腾讯云入口机一键部署              ║"
echo "║  目标：nginx 反代 + frps + systemd          ║"
echo "╚════════════════════════════════════════════╝"
echo ""

if [ "$(id -u)" -ne 0 ]; then
    echo "[!] 必须 root 运行"; exit 1
fi

mkdir -p "$LOG_DIR" "$DEPLOY_DIR" "$FRP_DIR"

# ─────────────────────────────────────────────────────────────
echo ""
echo "▶ 1/7 系统依赖"
apt-get update -qq
apt-get install -y -qq nginx wget curl unzip ufw

# ─────────────────────────────────────────────────────────────
echo ""
echo "▶ 2/7 下载 frp v${FRP_VERSION}"
if [ ! -x "${FRP_DIR}/frps" ]; then
    cd /tmp
    wget -q "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz" -O frp.tar.gz \
        || wget -q "https://mirrors.tuna.tsinghua.edu.cn/github-release/fatedier/frp/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz" -O frp.tar.gz
    tar xzf frp.tar.gz
    mv frp_${FRP_VERSION}_linux_amd64/* "${FRP_DIR}/"
    rm -rf frp_${FRP_VERSION}_linux_amd64 frp.tar.gz
    chmod +x ${FRP_DIR}/frps ${FRP_DIR}/frpc
    echo "  frp ${FRP_VERSION} 安装到 ${FRP_DIR}"
else
    echo "  frp 已存在，跳过下载"
fi

# ─────────────────────────────────────────────────────────────
echo ""
echo "▶ 3/7 写 frps 配置"
cat > ${FRP_DIR}/frps.toml <<'FRPS_EOF'
bindPort = 7000

auth.method = "token"
auth.token = "Dc_3jK9pQrL5xN7vM2hY8zT4wU6sE1aB"

allowPorts = [
  { start = 28000, end = 28010 },
]

webServer.addr = "127.0.0.1"
webServer.port = 7500
webServer.user = "admin"
webServer.password = "deepcoke_dash_2026"

log.to = "/var/log/deepcoke/frps.log"
log.level = "info"
log.maxDays = 7

transport.maxPoolCount = 5
FRPS_EOF
echo "  ${FRP_DIR}/frps.toml 已写入（token 在文件内，请妥善保管）"

# ─────────────────────────────────────────────────────────────
echo ""
echo "▶ 4/7 frps systemd 服务"
cat > /etc/systemd/system/deepcoke-frps.service <<'SVC_EOF'
[Unit]
Description=DeepCoke frp Server (Tencent Gateway)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/frp
ExecStart=/opt/frp/frps -c /opt/frp/frps.toml
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/deepcoke/frps.log
StandardError=append:/var/log/deepcoke/frps.err.log

[Install]
WantedBy=multi-user.target
SVC_EOF
systemctl daemon-reload
systemctl enable deepcoke-frps >/dev/null 2>&1
systemctl restart deepcoke-frps
sleep 2
if systemctl is-active --quiet deepcoke-frps; then
    echo "  frps 启动 OK (监听 7000)"
else
    echo "  [!] frps 启动失败，看 journalctl -u deepcoke-frps -n 30"
    exit 1
fi

# ─────────────────────────────────────────────────────────────
echo ""
echo "▶ 5/7 nginx 反代"
cat > /etc/nginx/sites-available/deepcoke <<'NGX_EOF'
limit_req_zone $binary_remote_addr zone=chat_limit:10m rate=30r/m;
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    client_max_body_size 50M;
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;

    root /var/www/deepcoke/dist;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~ ^/(login|register|logout)(/|$) {
        proxy_pass http://127.0.0.1:28000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Authorization $http_authorization;
    }

    location ~ ^/chat(/|$) {
        limit_req zone=chat_limit burst=5 nodelay;
        proxy_pass http://127.0.0.1:28000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Authorization $http_authorization;
        proxy_buffering off;
        proxy_set_header X-Accel-Buffering no;
    }

    location ~ ^/(new_session|user_sessions|messages|sessions|folders|rename_session|delete_session|face|all_coals_page|papers|chunk|paper_graph)(/|$) {
        limit_req zone=api_limit burst=20 nodelay;
        proxy_pass http://127.0.0.1:28000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header X-Accel-Buffering no;
    }

    location /voice/ {
        proxy_pass http://127.0.0.1:28001/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }

    access_log /var/log/nginx/deepcoke_access.log;
    error_log  /var/log/nginx/deepcoke_error.log;
}
NGX_EOF

ln -sf /etc/nginx/sites-available/deepcoke /etc/nginx/sites-enabled/deepcoke
rm -f /etc/nginx/sites-enabled/default

# 准备 web 根目录，先放个占位页
mkdir -p /var/www/deepcoke/dist
cat > /var/www/deepcoke/dist/index.html <<'HTML_EOF'
<!doctype html>
<html><head><meta charset="utf-8"><title>DeepCoke Gateway</title></head>
<body style="font-family:monospace;padding:40px;background:#0a0a0a;color:#9aa">
<h2>🚀 DeepCoke Gateway 已就绪</h2>
<p>nginx 反代 + frps 启动正常。</p>
<p>状态：等待 dbcloud 后端 frpc 接入隧道…</p>
<p>下一步：在 dbcloud 物理机上跑 <code>create_container.sh</code> 起后端容器。</p>
</body></html>
HTML_EOF
chown -R www-data:www-data /var/www/deepcoke

nginx -t
systemctl reload nginx
echo "  nginx 反代配置 OK"

# ─────────────────────────────────────────────────────────────
echo ""
echo "▶ 6/7 防火墙（ufw）"
ufw --force enable >/dev/null
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 7000/tcp comment 'frps'
echo "  开放: 22 / 80 / 7000"
echo "  ⚠️ 请同步在腾讯云控制台『防火墙』里也加上 80 和 7000（如果还没加）"

# ─────────────────────────────────────────────────────────────
echo ""
echo "▶ 7/7 自检"
sleep 1
echo "  nginx:      $(systemctl is-active nginx)"
echo "  frps:       $(systemctl is-active deepcoke-frps)"
echo "  公网入口:    http://$(curl -s -m 5 ifconfig.me 2>/dev/null || echo 106.52.177.125)/"
echo "  frps 监听:   $(ss -lntp 2>/dev/null | grep 7000 | head -1)"
echo ""
echo "╔════════════════════════════════════════════╗"
echo "║  ✓ 腾讯云端配置完成                          ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "下一步操作:"
echo "  1) 浏览器打开 http://106.52.177.125/ 应该看到 占位页"
echo "  2) 在 dbcloud 物理机 root shell 跑 create_container.sh"
echo "  3) 进容器后跑 setup_inside_container.sh"
echo ""
echo "FRP TOKEN（dbcloud 那边的 frpc.toml 要用同一个）："
echo "  Dc_3jK9pQrL5xN7vM2hY8zT4wU6sE1aB"
echo ""
