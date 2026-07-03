#!/usr/bin/env python3
"""
跑轮活动统计页 (hamster wheel activity dashboard)
读取 audio_activity.py 写的 CSV,展示每天跑轮时长/次数 + 每小时活跃柱状图。
独立 HTTP 服务(默认 8090),只读日志,不碰摄像头。
访问: http://<host>:8090/
"""
import argparse, csv, time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CFG = {}

def load():
    rows = []
    try:
        for r in csv.reader(open(CFG["log"])):
            if len(r) >= 2:
                rows.append(r)                     # [start_ts, dur, max_e, tag]
    except FileNotFoundError:
        pass
    return rows

def fmt(sec):
    sec = int(sec); h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return ("%dh%02dm" % (h, m)) if h else ("%dm%02ds" % (m, s))

def page():
    rows = load()
    per_day = defaultdict(lambda: [0.0, 0, 0.0])   # date -> [total_sec, bouts, longest]
    hourly = defaultdict(float)                     # hour -> total_sec (all days)
    for r in rows:
        try:
            ts = r[0]; dur = float(r[1])
            date = ts[:10]; hour = int(ts[11:13])
        except (ValueError, IndexError):
            continue
        per_day[date][0] += dur; per_day[date][1] += 1
        per_day[date][2] = max(per_day[date][2], dur)
        hourly[hour] += dur

    html = ["""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>🐹 跑轮统计</title><style>body{font-family:sans-serif;background:#111;color:#ddd;padding:12px}
h2,h3{color:#6cf}table{border-collapse:collapse;width:100%%;max-width:520px}
td,th{padding:6px 10px;border-bottom:1px solid #333;text-align:left}
.bar{background:#3a7;height:16px;border-radius:3px;display:inline-block}
.hr{color:#888;width:38px;display:inline-block}</style></head><body>"""]
    html.append("<h2>🐹🎡 仓鼠跑轮统计</h2><p style='color:#888'>更新于 %s</p>"
                % time.strftime("%Y-%m-%d %H:%M"))

    # 每天汇总
    html.append("<h3>每天</h3><table><tr><th>日期</th><th>总时长</th><th>次数</th><th>最长一段</th></tr>")
    for d in sorted(per_day, reverse=True)[:14]:
        tot, n, lng = per_day[d]
        html.append("<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>"
                    % (d, fmt(tot), n, fmt(lng)))
    html.append("</table>")

    # 每小时活跃(几点最爱跑)
    mx = max(hourly.values()) if hourly else 1
    html.append("<h3>每小时活跃(累计)</h3>")
    for h in range(24):
        w = int(hourly.get(h, 0) / mx * 300)
        html.append("<div><span class='hr'>%02d:00</span>"
                    "<span class='bar' style='width:%dpx'></span> %s</div>"
                    % (h, w, fmt(hourly.get(h, 0)) if hourly.get(h) else ""))
    html.append("</body></html>")
    return "".join(html).encode("utf-8")

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", type=int, default=8090)
    ap.add_argument("--log", default="/home/pi/hamster_wheel.csv")
    a = ap.parse_args()
    CFG["log"] = a.log
    print("跑轮统计页: http://<host>:%d/" % a.port)
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()

if __name__ == "__main__":
    main()
