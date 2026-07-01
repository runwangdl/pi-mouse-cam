#!/usr/bin/env python3
"""
pi-mouse-cam / 检测版 —— USB 摄像头 + 背景差分,框出移动的仓鼠并直播。

清晰度与速度解耦:
  - 以高分辨率采集并直播(清晰)
  - 检测(MOG2 背景差分)只在缩小的副本上做(快),框再按比例放大画回高清帧
这样在树莓派 3 上既能看高清、检测又跟得上。

用法:
    python3 mjpeg_detect.py --width 1280 --height 720 --proc-width 320
    python3 mjpeg_detect.py --roi 0,0,0.47,1        # 只检测笼子区域

浏览器打开 http://<pi-ip>:8000/ 。
"""
import argparse
import threading
import time

import cv2
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INDEX_HTML = b"""<!doctype html><html><head><meta charset="utf-8">
<title>pi-mouse-cam detect</title><style>body{margin:0;background:#111;
display:flex;justify-content:center;align-items:center;height:100vh}
img{max-width:100%;max-height:100vh}</style></head>
<body><img src="/stream"></body></html>"""

_latest = {"jpg": None}
_cond = threading.Condition()


def capture_loop(device, disp_w, disp_h, proc_w, min_area, quality, roi):
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, disp_w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, disp_h)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    bg = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=30,
                                            detectShadows=False)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    active_frames = 0
    total_frames = 0

    while True:
        ok, frame = cap.read()               # 高清帧(用于显示)
        if not ok:
            time.sleep(0.1)
            continue
        H, W = frame.shape[:2]

        # 缩小副本做检测,记住放大倍数 k
        small = cv2.resize(frame, (proc_w, int(H * proc_w / W)))
        sh, sw = small.shape[:2]
        k = W / float(sw)

        # ROI(小数 0~1),在小图上裁出检测区域
        if roi:
            rx1, ry1 = int(roi[0] * sw), int(roi[1] * sh)
            rx2, ry2 = int(roi[2] * sw), int(roi[3] * sh)
        else:
            rx1, ry1, rx2, ry2 = 0, 0, sw, sh
        sub = small[ry1:ry2, rx1:rx2]

        fg = bg.apply(sub)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
        fg = cv2.dilate(fg, kernel, iterations=1)
        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        big = [c for c in contours if cv2.contourArea(c) > min_area]

        # ROI 边框(按 k 放大到高清帧)
        if roi:
            cv2.rectangle(frame, (int(rx1 * k), int(ry1 * k)),
                          (int(rx2 * k), int(ry2 * k)), (120, 120, 120), 1)

        total_frames += 1
        detected = bool(big)
        if detected:
            active_frames += 1
            c = max(big, key=cv2.contourArea)
            x, y, bw, bh = cv2.boundingRect(c)
            x, y = x + rx1, y + ry1
            # 小图坐标 → 高清坐标
            X, Y, BW, BH = int(x * k), int(y * k), int(bw * k), int(bh * k)
            cv2.rectangle(frame, (X, Y), (X + BW, Y + BH), (0, 255, 0), 2)
            cv2.circle(frame, (X + BW // 2, Y + BH // 2), 4, (0, 255, 0), -1)
            cv2.putText(frame, "Hamster", (X, max(Y - 8, 16)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        status = "ACTIVE" if detected else "idle"
        color = (0, 255, 0) if detected else (170, 170, 170)
        act_pct = 100.0 * active_frames / max(total_frames, 1)
        cv2.putText(frame, "%s  activity:%.0f%%  %s" %
                    (status, act_pct, time.strftime("%H:%M:%S")),
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

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
    ap.add_argument("--width", type=int, default=1280, help="显示/直播宽度(清晰度)")
    ap.add_argument("--height", type=int, default=720, help="显示/直播高度")
    ap.add_argument("--proc-width", type=int, default=320,
                    help="检测处理宽度(越小越快,与清晰度无关)")
    ap.add_argument("--min-area", type=int, default=200)
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument("--roi", default=None,
                    help="只检测该区域,4 个 0~1 小数 x1,y1,x2,y2")
    args = ap.parse_args()

    roi = None
    if args.roi:
        roi = [float(v) for v in args.roi.split(",")]
        assert len(roi) == 4, "--roi 需要 4 个 0~1 小数"

    t = threading.Thread(target=capture_loop,
                         args=(args.device, args.width, args.height,
                               args.proc_width, args.min_area, args.quality,
                               roi),
                         daemon=True)
    t.start()
    print("检测直播中(显示 %dx%d / 检测 %dpx): http://<pi-ip>:%d/"
          % (args.width, args.height, args.proc_width, args.port))
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
