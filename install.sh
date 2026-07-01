#!/usr/bin/env bash
# 在树莓派上安装 pi-mouse-cam 为开机自启的 systemd 服务。
# 用法:sudo ./install.sh
set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 sudo 运行:sudo ./install.sh" >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_SRC="$REPO_DIR/mjpeg-stream.service"
SERVICE_DST="/etc/systemd/system/mjpeg-stream.service"
RUN_USER="${SUDO_USER:-pi}"

# 把服务文件里的脚本路径和用户替换成实际值
sed \
  -e "s#/home/pi/pi-mouse-cam/mjpeg_stream.py#$REPO_DIR/mjpeg_stream.py#" \
  -e "s#^User=pi#User=$RUN_USER#" \
  "$SERVICE_SRC" > "$SERVICE_DST"

systemctl daemon-reload
systemctl enable mjpeg-stream.service
systemctl restart mjpeg-stream.service
sleep 2
systemctl --no-pager status mjpeg-stream.service | head -n 8

IP=$(hostname -I | awk '{print $1}')
echo
echo "✅ 已安装并启动。浏览器打开: http://$IP:8000/"
