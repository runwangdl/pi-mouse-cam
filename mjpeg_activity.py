#!/usr/bin/env python3
"""
夜间活动检查器 (hamster night activity monitor)
================================================
- 用背景差分测"运动量"(不依赖精确框,避开框错问题)
- 判定 活跃/安静,记录活动时间到 CSV
- 活跃时自动拍照存盘(带时间戳)
- 夜间活跃时通过 ntfy 推送通知 + 照片到手机
- 同时提供直播:  /        网页
                 /stream   MJPEG
                 /activity 今日活动时间线

用法: python3 mjpeg_activity.py [参数见 argparse]
浏览器/手机(经 Tailscale): http://hamster-pi:8000/
"""
import argparse
import os
import threading
import time
import csv
import urllib.request

import cv2

_latest = {"jpg": None}
_cond = threading.Condition()

INDEX_HTML = ("""<!doctype html><html><head><meta charset="utf-8">
<title>hamster activity</title><style>body{margin:0;background:#111;color:#ccc;
font-family:sans-serif}img{display:block;max-width:100%;margin:auto}
a{color:#6cf}</style></head><body><img src="/stream">
<p style="text-align:center"><a href="/activity">今日活动时间线</a></p>
</body></html>""").encode("utf-8")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def is_night(night_start, night_end):
    h = int(time.strftime("%H"))
    if night_start <= night_end:
        return night_start <= h < night_end
    return h >= night_start or h < night_end       # 跨午夜


def ntfy_push(topic, title, msg, jpg=None):
    if not topic:
        return
    url = "https://ntfy.sh/" + topic
    try:
        headers = {"Title": title.encode("utf-8"),
                   "Priority": "default", "Tags": "hamster"}
        if jpg is not None:
            headers["Filename"] = "hamster.jpg"
            data = jpg
        else:
            data = msg.encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass


def capture_loop(cfg):
    cap = cv2.VideoCapture(cfg.device, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    bg = cv2.createBackgroundSubtractorMOG2(history=400, varThreshold=25,
                                            detectShadows=False)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    os.makedirs(cfg.snap_dir, exist_ok=True)
    active_run = 0          # 连续活跃帧数
    last_notify = 0.0
    bout_open = False       # 当前是否处于一次活跃 bout

    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.1); continue
        H, W = frame.shape[:2]
        proc = cv2.resize(frame, (320, int(H * 320 / W)))
        ph, pw = proc.shape[:2]

        # ROI(小数 0~1);默认全帧
        if cfg.roi:
            rx1, ry1 = int(cfg.roi[0]*pw), int(cfg.roi[1]*ph)
            rx2, ry2 = int(cfg.roi[2]*pw), int(cfg.roi[3]*ph)
        else:
            rx1, ry1, rx2, ry2 = 0, 0, pw, ph
        sub = proc[ry1:ry2, rx1:rx2]

        fg = bg.apply(sub)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
        motion = float((fg > 0).sum()) / max(fg.size, 1)     # 运动量 0~1
        active = motion > cfg.thresh

        # 叠加显示:运动量条 + 状态(不画会框错的检测框)
        night = is_night(cfg.night_start, cfg.night_end)
        status = "ACTIVE" if active else "quiet"
        color = (0, 255, 0) if active else (150, 150, 150)
        if cfg.roi:
            k = W / float(pw)
            cv2.rectangle(frame, (int(rx1*k), int(ry1*k)),
                          (int(rx2*k), int(ry2*k)), (90, 90, 90), 1)
        cv2.putText(frame, "%s  motion:%.1f%%  %s%s" %
                    (status, motion*100, time.strftime("%H:%M:%S"),
                     "  [NIGHT]" if night else ""),
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        barw = int(min(motion / max(cfg.thresh*4, 1e-6), 1.0) * (W - 20))
        cv2.rectangle(frame, (10, 40), (10+barw, 52), color, -1)

        # —— 活跃事件逻辑 ——
        active_run = active_run + 1 if active else 0
        if active_run == cfg.min_frames and not bout_open:
            bout_open = True
            ts = now()
            # 1) 记 CSV
            with open(cfg.log, "a", newline="") as f:
                csv.writer(f).writerow([ts, "%.4f" % motion, "night" if night else "day"])
            # 2) 存照片
            ok2, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            snap = None
            if ok2:
                snap = jpg.tobytes()
                fn = os.path.join(cfg.snap_dir,
                                  time.strftime("%Y%m%d_%H%M%S") + ".jpg")
                open(fn, "wb").write(snap)
            # 3) 夜间 + 冷却期外 → 推送
            if night and (time.time() - last_notify) > cfg.cooldown:
                last_notify = time.time()
                ntfy_push(cfg.ntfy, "🐹 仓鼠夜间活动 %s" % ts,
                          "motion %.1f%%" % (motion*100), snap)
        if not active and active_run == 0:
            bout_open = False

        ok3, out = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, cfg.quality])
        if ok3:
            with _cond:
                _latest["jpg"] = out.tobytes()
                _cond.notify_all()


def make_handler(cfg):
    from http.server import BaseHTTPRequestHandler

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", INDEX_HTML); return
            if self.path == "/activity":
                self._send(200, "text/html; charset=utf-8", self._activity()); return
            if self.path != "/stream":
                self.send_error(404); return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache"); self.end_headers()
            try:
                while True:
                    with _cond:
                        _cond.wait(timeout=5); jpg = _latest["jpg"]
                    if jpg is None: continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(b"Content-Length: %d\r\n\r\n" % len(jpg))
                    self.wfile.write(jpg); self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _send(self, code, ctype, body):
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)

        def _activity(self):
            today = time.strftime("%Y-%m-%d")
            rows = []
            try:
                for r in csv.reader(open(cfg.log)):
                    if r and r[0].startswith(today):
                        rows.append(r)
            except FileNotFoundError:
                pass
            html = "<html><head><meta charset='utf-8'><style>body{font-family:sans-serif;background:#111;color:#ccc}</style></head><body>"
            html += "<h3>今日活动 %s(共 %d 次活跃事件)</h3><ul>" % (today, len(rows))
            for r in rows[-100:]:
                html += "<li>%s  运动 %.1f%%  [%s]</li>" % (r[0], float(r[1])*100, r[2] if len(r) > 2 else "")
            html += "</ul></body></html>"
            return html.encode("utf-8")

        def log_message(self, *a): pass
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-d", "--device", default="/dev/video0")
    ap.add_argument("-p", "--port", type=int, default=8000)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument("--roi", default=None, help="4 个 0~1 小数 x1,y1,x2,y2;默认全帧")
    ap.add_argument("--thresh", type=float, default=0.006, help="运动量阈值(前景占比)")
    ap.add_argument("--min-frames", type=int, default=5, help="连续这么多帧活跃才算一次事件")
    ap.add_argument("--cooldown", type=float, default=300, help="两次推送最短间隔(秒)")
    ap.add_argument("--night-start", type=int, default=20)
    ap.add_argument("--night-end", type=int, default=8)
    ap.add_argument("--ntfy", default="", help="ntfy 主题名(手机订阅它收通知)")
    ap.add_argument("--log", default="/home/pi/hamster_activity.csv")
    ap.add_argument("--snap-dir", default="/home/pi/snaps")
    cfg = ap.parse_args()
    if cfg.roi:
        cfg.roi = [float(v) for v in cfg.roi.split(",")]

    threading.Thread(target=capture_loop, args=(cfg,), daemon=True).start()
    from http.server import ThreadingHTTPServer
    print("活动监控中: http://<host>:%d/  夜间 %d:00-%d:00  ntfy=%s"
          % (cfg.port, cfg.night_start, cfg.night_end, cfg.ntfy or "关"))
    ThreadingHTTPServer(("0.0.0.0", cfg.port), make_handler(cfg)).serve_forever()


if __name__ == "__main__":
    main()
