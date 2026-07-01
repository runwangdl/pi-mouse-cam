#!/usr/bin/env python3
"""
pi-mouse-cam — 极简 USB 摄像头 MJPEG 直播服务器
================================================

只依赖 Python3 标准库 + v4l2-ctl,无需 OpenCV / ffmpeg / 联网即可运行。
适合树莓派 + 普通 UVC USB 摄像头,把画面通过局域网实时直播到浏览器。

用法:
    python3 mjpeg_stream.py                       # 默认 /dev/video0, 1280x720, :8000
    python3 mjpeg_stream.py -d /dev/video0 -W 1280 -H 720 -p 8000

然后在同一局域网的任意设备浏览器打开:
    http://<树莓派IP>:8000/

原理:
    v4l2-ctl 把摄像头的 MJPG(本身就是 JPEG)帧连续输出到 stdout,
    本脚本按 JPEG 头(FFD8)尾(FFD9)切分,再以
    multipart/x-mixed-replace 的方式喂给浏览器 —— 即 MJPEG 直播。
"""
import argparse
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INDEX_HTML = b"""<!doctype html>
<html><head><meta charset="utf-8"><title>pi-mouse-cam</title>
<style>body{margin:0;background:#111;display:flex;justify-content:center;
align-items:center;height:100vh}img{max-width:100%;max-height:100vh}</style>
</head><body><img src="/stream"></body></html>"""


def mjpeg_frames(device, width, height):
    """让 v4l2-ctl 连续输出 MJPG 帧到 stdout,按 JPEG 边界切分后逐帧 yield。"""
    proc = subprocess.Popen(
        ["v4l2-ctl", "-d", device,
         "--set-fmt-video=width=%d,height=%d,pixelformat=MJPG" % (width, height),
         "--stream-mmap", "--stream-count=0", "--stream-to=-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    buf = b""
    try:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                start = buf.find(b"\xff\xd8")          # JPEG SOI
                end = buf.find(b"\xff\xd9", start + 2)   # JPEG EOI
                if start != -1 and end != -1:
                    yield buf[start:end + 2]
                    buf = buf[end + 2:]
                else:
                    break
    finally:
        proc.terminate()                                 # 客户端断开时释放摄像头


def make_handler(device, width, height):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(INDEX_HTML)))
                self.end_headers()
                self.wfile.write(INDEX_HTML)
                return
            if self.path != "/stream":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for jpg in mjpeg_frames(device, width, height):
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(b"Content-Length: %d\r\n\r\n" % len(jpg))
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass
    return Handler


def main():
    ap = argparse.ArgumentParser(description="USB camera MJPEG live stream")
    ap.add_argument("-d", "--device", default="/dev/video0")
    ap.add_argument("-W", "--width", type=int, default=1280)
    ap.add_argument("-H", "--height", type=int, default=720)
    ap.add_argument("-p", "--port", type=int, default=8000)
    args = ap.parse_args()

    handler = make_handler(args.device, args.width, args.height)
    print("pi-mouse-cam 直播中: http://<pi-ip>:%d/  (设备 %s @ %dx%d)"
          % (args.port, args.device, args.width, args.height))
    ThreadingHTTPServer(("0.0.0.0", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
