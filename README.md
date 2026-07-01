# pi-mouse-cam

用树莓派 + 普通 USB 摄像头搭一个**局域网实时监控**(比如看老鼠🐭)。
零重型依赖:只用 **Python3 标准库 + `v4l2-ctl`**,不需要 OpenCV / ffmpeg / motion,
甚至树莓派**不联网也能跑**。在同网络的任意设备浏览器打开一个网址即可看直播。

```
USB 摄像头 ──▶ 树莓派 (v4l2-ctl 抓 MJPG) ──▶ HTTP MJPEG ──▶ 浏览器实时看
```

## 硬件

- 树莓派(Pi 3 及以上,有网口/WiFi)
- 一个 UVC 标准 USB 摄像头(即插即用,`/dev/video0`)
- 5V/2.5A 以上的**好电源 + 好线**(欠压会写坏 SD 卡,别用电脑 USB 口供电)

> 注意:并口 DVP 摄像头(如 OV5640/ATK-MC5640)**接不了树莓派**(树莓派是 CSI/USB 接口),本项目用 **USB** 摄像头。

## 快速开始

树莓派上(已装 Raspberry Pi OS):

```bash
# 1. 确认摄像头被识别
ls /dev/video0
v4l2-ctl --list-formats-ext -d /dev/video0   # 看支持的分辨率/格式(需含 MJPG)

# 2. 拉取本项目并启动直播
git clone <this-repo> pi-mouse-cam && cd pi-mouse-cam
python3 mjpeg_stream.py            # 默认 /dev/video0, 1280x720, 端口 8000
```

在同一局域网的电脑/手机浏览器打开:

```
http://<树莓派IP>:8000/
```

查看树莓派 IP:`hostname -I`。

## 参数

```bash
python3 mjpeg_stream.py -d /dev/video0 -W 1280 -H 720 -p 8000
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `-d` | 摄像头设备 | `/dev/video0` |
| `-W` | 宽 | `1280` |
| `-H` | 高 | `720` |
| `-p` | 端口 | `8000` |

想省带宽/更流畅可用 `-W 640 -H 480`。

## 开机自启(systemd,推荐)

让直播开机自动运行、崩了自动重启,不依赖 SSH 会话:

```bash
sudo ./install.sh          # 安装并启用 mjpeg-stream.service
systemctl status mjpeg-stream
```

之后每次树莓派开机,浏览器打开 `http://<树莓派IP>:8000/` 即可。

## Headless 首次配置(无键盘/显示器)

用另一台电脑烧好 SD 卡后,在 **boot 分区**放这几个文件即可免键盘配置:

- 空文件 `ssh` → 开启 SSH
- `userconf.txt` → 建用户:`用户名:$(echo '密码' | openssl passwd -6 -stdin)`
- 有线最省心:直接把树莓派插到路由器,开机自动拿 IP;`ssh 用户名@raspberrypi.local`

> 较新的 Raspberry Pi OS(Bookworm/Trixie)WiFi 改用 NetworkManager,
> 老的 `wpa_supplicant.conf` 方式不一定生效 —— **网线最稳**。

## 工作原理

摄像头的 `MJPG` 像素格式本身每帧就是一张完整 JPEG。`v4l2-ctl --stream-to=-`
把这些帧连续写到 stdout,脚本按 JPEG 的开始标记 `FF D8` 和结束标记 `FF D9`
切分出单帧,再用 HTTP `multipart/x-mixed-replace` 逐帧推给浏览器 —— 这就是
最经典的 MJPEG 直播,浏览器原生支持,无需任何前端播放器。

## 后续可玩

- 移动侦测 + 自动录像(接 `motion` 或在本脚本里加帧差检测)
- 夜视(换红外摄像头 + 补光)
- 简单目标追踪(OpenCV 背景差分,框出移动的老鼠、记录活动量)

## License

MIT
