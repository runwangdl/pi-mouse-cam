#!/usr/bin/env bash
# 安装 HamiCam 新增服务: 总览页(8080) + 温湿度 + (可选)雷达
# 用法: sudo ./install_hamicam.sh            只装总览页 + 温湿度
#       sudo ./install_hamicam.sh --radar    再加雷达
# 不动已有的 mjpeg-activity / audio-wheel / wheel-stats。
# 日志路径和已有服务一样写死在 /home/pi,用户名不是 pi 时要改 *.service 里的参数。
set -e
[ "$(id -u)" -eq 0 ] || { echo "请用 sudo 运行" >&2; exit 1; }
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_USER="${SUDO_USER:-pi}"
UNITS="hamicam env-sensor"
[ "$1" = "--radar" ] && UNITS="$UNITS radar-mr60"

if [ ! -e /dev/i2c-1 ]; then
  echo "⚠ /dev/i2c-1 不存在:先 sudo raspi-config → Interface → I2C 打开,再重跑。温湿度服务会起不来。"
fi

for u in $UNITS; do
  sed -e "s#/home/pi/pi-mouse-cam#$REPO_DIR#" -e "s#^User=pi#User=$RUN_USER#" \
      "$REPO_DIR/$u.service" > /etc/systemd/system/$u.service
done
systemctl daemon-reload
for u in $UNITS; do systemctl enable --now $u.service; done
sleep 2
for u in $UNITS; do systemctl --no-pager --lines=0 status $u.service | head -n 3; done
echo
echo "✅ 总览页: http://$(hostname):8080/  (Tailscale 下手机也能开)"
