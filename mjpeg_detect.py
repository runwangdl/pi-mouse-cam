#!/usr/bin/env python3
"""
pi-mouse-cam / 检测版 —— USB 摄像头 + 背景差分,框出移动的仓鼠并直播。

在静止背景(笼子)下用 OpenCV MOG2 背景差分分割出移动目标,
框出最大的运动区域(=仓鼠),叠加"活跃/静止"状态与活动量,
再以 MJPEG 直播到浏览器。适合树莓派 3(处理分辨率降到 ~640 宽,近实时)。

用法:
    python3 mjpeg_detect.py                 # 默认 /dev/video0, :8000
    python3 mjpeg_detect.py -d /dev/video0 -p 8000 --min-area 500

浏览器打开 http://<pi-ip>:8000/ 即可看到带检测框的直播。
"""
import argparse
import threading
import time

import cv2
import numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INDEX_HTML = b"""<!doctype html><html><head><meta charset="utf-8">
<title>pi-mouse-cam detect</title><style>body{margin:0;background:#111;
display:flex;justify-content:center;align-items:center;height:100vh}
img{max-width:100%;max-height:100vh}</style></head>
<body><img src="/stream"></body></html>"""

# 共享的最新一帧(带标注的 JPEG 字节)
_latest = {"jpg": None}
_cond = threading.Condition()


def capture_loop(device, proc_w, min_area, quality, roi):
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)      # 只留最新帧,降延迟

    # 背景差分器:学习静止背景,把移动的仓鼠减出来
    bg = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=30,
                                            detectShadows=False)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    active_frames = 0
    total_frames = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.1)
            continue

        # 处理分辨率越小越快(MOG2/形态学/编码都随像素数平方级下降)
        h, w = frame.shape[:2]
        if w != proc_w:
            frame = cv2.resize(frame, (proc_w, int(h * proc_w / w)))
        h, w = frame.shape[:2]

        # ROI:只在笼子区域内做检测,忽略画面外(手/衣服/笔记本)的动静
        if roi:
            rx1, ry1 = int(roi[0] * w), int(roi[1] * h)
            rx2, ry2 = int(roi[2] * w), int(roi[3] * h)
        else:
            rx1, ry1, rx2, ry2 = 0, 0, w, h
        sub = frame[ry1:ry2, rx1:rx2]

        fg = bg.apply(sub)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
        fg = cv2.dilate(fg, kernel, iterations=1)

        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        big = [c for c in contours if cv2.contourArea(c) > min_area]

        # 画出 ROI 边框(灰色),让你看清监测区域
        if roi:
            cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), (120, 120, 120), 1)

        total_frames += 1
        detected = bool(big)
        if detected:
            active_frames += 1
            c = max(big, key=cv2.contourArea)
            x, y, bw, bh = cv2.boundingRect(c)
            x, y = x + rx1, y + ry1                 # 偏移回全图坐标
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
            cx, cy = x + bw // 2, y + bh // 2
            cv2.circle(frame, (cx, cy), 3, (0, 255, 0), -1)
            cv2.putText(frame, "Hamster", (x, max(y - 8, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # 顶部状态条
        status = "ACTIVE" if detected else "idle"
        color = (0, 255, 0) if detected else (160, 160, 160)
        act_pct = 100.0 * active_frames / max(total_frames, 1)
        cv2.putText(frame, "%s  activity:%.0f%%  %s" %
                    (status, act_pct, time.strftime("%H:%M:%S")),
                    (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        ok, jpg = cv2.imencode(".jpg", frame,
                               [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok:
            with _cond:
                _latest["jpg"] = jpg.tobytes()
                _cond.notify_all()


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
            while True:
                with _cond:
                    _cond.wait(timeout=5)
                    jpg = _latest["jpg"]
                if jpg is None:
                    continue
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(b"Content-Length: %d\r\n\r\n" % len(jpg))
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser(description="Hamster detection MJPEG stream")
    ap.add_argument("-d", "--device", default="/dev/video0")
    ap.add_argument("-p", "--port", type=int, default=8000)
    ap.add_argument("--proc-width", type=int, default=320,
                    help="处理/显示宽度(越小越流畅;320≈实时,640更清晰但慢)")
    ap.add_argument("--min-area", type=int, default=200,
                    help="最小运动区域面积(过滤噪声,越大越不敏感)")
    ap.add_argument("--quality", type=int, default=65,
                    help="JPEG 质量(越低编码越快、带宽越小)")
    ap.add_argument("--roi", default=None,
                    help="只检测该区域,4 个 0~1 小数 x1,y1,x2,y2(如笼子在左半:0,0,0.47,1)")
    args = ap.parse_args()

    roi = None
    if args.roi:
        roi = [float(v) for v in args.roi.split(",")]
        assert len(roi) == 4, "--roi 需要 4 个用逗号分隔的 0~1 小数"

    t = threading.Thread(target=capture_loop,
                         args=(args.device, args.proc_width, args.min_area,
                               args.quality, roi),
                         daemon=True)
    t.start()
    print("检测直播中: http://<pi-ip>:%d/" % args.port)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
