#!/usr/bin/env bash
set -euo pipefail
INSTALL_DIR="/opt/sentinelx"
CONFIG_DIR="/etc/sentinelx"
DATA_DIR="/var/lib/sentinelx"
LOG_DIR="/var/log/sentinelx"
SERVICE_NAME="sentinelx"
RUN_USER="sentinelx"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root" >&2
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip curl ca-certificates

id -u "$RUN_USER" >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$RUN_USER"

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$DATA_DIR/uploads" "$LOG_DIR"
cp -r "$SRC_DIR"/* "$INSTALL_DIR"/
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

if [ ! -f "$CONFIG_DIR/sentinelx.env" ]; then
  cp "$INSTALL_DIR/examples/sentinelx.env.example" "$CONFIG_DIR/sentinelx.env"
  chmod 640 "$CONFIG_DIR/sentinelx.env"
fi

cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=SentinelX Core
After=network.target

[Service]
User=${RUN_USER}
Group=${RUN_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${CONFIG_DIR}/sentinelx.env
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn agent:app --host 127.0.0.1 --port \${AGENT_PORT:-8091}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

chown -R ${RUN_USER}:${RUN_USER} "$INSTALL_DIR" "$DATA_DIR" "$LOG_DIR"
chmod +x "$INSTALL_DIR/run.sh" "$INSTALL_DIR/install.sh" "$INSTALL_DIR/bin/sentinelx-safe-edit"
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}
echo "Installed SentinelX Core"
echo "Edit config: ${CONFIG_DIR}/sentinelx.env"
echo "Status: systemctl status ${SERVICE_NAME}"
