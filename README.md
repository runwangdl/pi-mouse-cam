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

## HamiCam 扩展(总览页 + 温湿度 + 雷达)

这个仓库也是 [HamiCam](https://github.com/runwangdl) 智能仓鼠监控的原型固件。新增三个服务,都只读/写日志,不影响已有的直播、活动检测和跑轮统计:

| 服务 | 脚本 | 作用 | 硬件 |
|------|------|------|------|
| `hamicam` | `hamicam.py` | 总览页 `:8080`:视频 + 状态 + 温湿度 + 呼吸/心率 + 今日跑轮/活动;`/api/state` 出 JSON | 无 |
| `env-sensor` | `env_sensor.py` | 每 30 s 记一次温湿度到 `~/hamster_env.csv` | AHT20 (I²C) |
| `radar-mr60` | `radar_mr60.py` | 读 60 GHz 雷达的呼吸率/心率/距离,写 `~/hamster_radar.{csv,json}` | Seeed MR60BHA2 (UART) |

```bash
sudo raspi-config            # Interface → I2C 打开(温湿度要);Serial:关登录 shell、开硬件串口(雷达要)
sudo ./install_hamicam.sh    # 装总览页 + 温湿度
sudo ./install_hamicam.sh --radar   # 雷达到货后再加
```

手机(Tailscale)打开 `http://hamster-pi:8080/`。雷达或温湿度没接时,对应卡片显示 “—”,不会显示旧数据。

AHT20 接线:VIN→3V3 (pin 1),GND→pin 6,SDA→GPIO2 (pin 3),SCL→GPIO3 (pin 5)。
没有传感器时可以 `python3 env_sensor.py --fake --log /tmp/env.csv` 造假数据调页面。

MR60BHA2 注意:
- 出厂是和 XIAO ESP32C6 装在一起的套件。要么拔掉 XIAO 从排针直接接 Pi 的 UART,要么给 XIAO 刷串口透传,Pi 读 USB 串口(`--dev /dev/ttyACM0`)。
- 帧格式按 Seeed 开源库写的,**还没在实物上验证**。到货后先跑 `python3 radar_mr60.py --dump` 看原始帧。
- 它的算法是按人调的。仓鼠心率 250–500 bpm,读数大概率不可信,只当实验数据看。

### 夜视

套件式 850/940 nm 红外补光板自带光敏电阻,天黑自动亮,插 USB 或 5 V 供电即可,不需要 GPIO。
普通 USB 摄像头镜头里多半有红外截止滤光片,红外可能拍不到;先试,拍不到再换无滤光片 (NoIR) 摄像头。

## License

MIT
