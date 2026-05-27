#!/usr/bin/env bash
set -euo pipefail

# ============================================
# AutoChat — Linux 一键部署脚本
# 支持 systemd 自启 / Docker 两种模式
# ============================================

REPO_URL="https://github.com/Wakelight56/260524learn.git"
INSTALL_DIR="/opt/autochat"
MODE="${1:-systemd}"  # systemd | docker

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[*]${NC} $1"; }
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# --- 前置检查 ---
command -v python3 >/dev/null 2>&1 || err "需要 python3，请先安装"
command -v git     >/dev/null 2>&1 || err "需要 git，请先安装"

# --- 克隆/更新代码 ---
if [ -d "$INSTALL_DIR/.git" ]; then
    log "更新代码..."
    cd "$INSTALL_DIR" && git pull
else
    log "克隆代码到 $INSTALL_DIR ..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# --- 创建 Python 虚拟环境 ---
log "创建虚拟环境..."
python3 -m venv venv
source venv/bin/activate
ok "虚拟环境已激活"

# --- 安装依赖 ---
log "安装 Python 依赖..."
pip install -r requirements.txt --upgrade pip
ok "依赖安装完成"

# --- 创建本地配置（从模板）---
CONFIG_FILE="config/config.local.json"
if [ ! -f "$CONFIG_FILE" ]; then
    log "创建本地配置模板: $CONFIG_FILE"
    cat > "$CONFIG_FILE" << 'EOF'
{
  "onebot": {
    "host": "127.0.0.1",
    "port": 3001,
    "access_token": ""
  },
  "ai": {
    "provider": "openai",
    "openai": {
      "api_key": "在此填入你的API Key",
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-3.5-turbo",
      "max_tokens": 2000,
      "temperature": 0.7
    },
    "claude": {
      "api_key": "",
      "base_url": "https://api.anthropic.com",
      "model": "claude-sonnet-4-6",
      "max_tokens": 2000,
      "temperature": 0.7
    }
  },
  "bot": {
    "name": "AutoChat",
    "nickname": ["AI助手"],
    "master_qq": 0,
    "auto_reply_groups": [],
    "auto_reply_private": true,
    "trigger_prefix": "",
    "trigger_at_mention": true,
    "enable_memory": true,
    "max_history": 50
  }
}
EOF
    echo -e "  ${RED}⚠ 请编辑 $CONFIG_FILE 填入你的 API Key 和 QQ 配置${NC}"
fi

# --- 安装模式选择 ---
if [ "$MODE" = "systemd" ]; then
    log "配置 systemd 自启服务..."

    # 获取当前用户
    RUN_USER="${SUDO_USER:-$(whoami)}"
    RUN_HOME=$(eval echo "~$RUN_USER")

    sudo tee /etc/systemd/system/autochat.service > /dev/null << EOF
[Unit]
Description=AutoChat QQ AI Robot
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable autochat
    log "启动 autochat 服务..."
    sudo systemctl start autochat

    ok "systemd 服务已安装并启动"
    echo ""
    echo "  管理命令:"
    echo "    sudo systemctl status autochat   # 查看状态"
    echo "    sudo systemctl restart autochat  # 重启"
    echo "    sudo journalctl -u autochat -f   # 查看实时日志"
    echo ""

elif [ "$MODE" = "docker" ]; then
    log "构建 Docker 镜像..."
    command -v docker >/dev/null 2>&1 || err "需要 docker，请先安装"
    sudo docker build -t autochat .
    ok "Docker 镜像已构建"
    echo ""
    echo "  运行:"
    echo "    docker run -d --name autochat \\"
    echo "      -v \$(pwd)/config:/app/config \\"
    echo "      -v \$(pwd)/memory:/app/memory \\"
    echo "      -v \$(pwd)/logs:/app/logs \\"
    echo "      --restart unless-stopped \\"
    echo "      autochat"
fi

ok "AutoChat 部署完成！"
