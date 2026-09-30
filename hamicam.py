#!/usr/bin/env python3
"""
HamiCam 总览页 —— 视频 + 状态 + 温湿度 + 雷达 + 今日记录
=========================================================
只读其他服务写的日志,不碰摄像头/麦克风/传感器:
  视频      http://<同主机>:8000/stream     (mjpeg_activity.py)
  活动事件  hamster_activity.csv            (mjpeg_activity.py)
  跑轮      hamster_wheel.csv               (audio_activity.py)
  温湿度    hamster_env.csv                 (env_sensor.py)
  雷达      hamster_radar.json              (radar_mr60.py,可选)
页面:  /           手机友好总览(照 05HamView/app/mockup 排版)
接口:  /api/state  JSON,字段对齐 docs/07_app_design.md 的数据契约
纯标准库。访问: http://hamster-pi:8080/  (Tailscale)
"""
import argparse, csv, json, os, time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CFG = None
RADAR_STALE_S = 10
WHEEL_RECENT_S = 90
ACTIVE_RECENT_S = 180


def read_csv(path):
    try:
        with open(path, newline="") as f:
            return [r for r in csv.reader(f) if r]
    except FileNotFoundError:
        return []


def ts_epoch(s):
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return 0.0


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_night(a, b):
    h = int(time.strftime("%H"))
    return (a <= h < b) if a <= b else (h >= a or h < b)


def state():
    now = time.time()
    today = time.strftime("%Y-%m-%d")

    act = read_csv(CFG.activity_log)
    wheel = read_csv(CFG.wheel_log)
    env = read_csv(CFG.env_log)

    # 温湿度:最新一条,超过 5 分钟算失效
    env_out = {"t_c": None, "rh": None, "age_s": None}
    if env:
        r = env[-1]
        age = now - ts_epoch(r[0])
        env_out = {"t_c": num(r[1]) if age < 300 else None,
                   "rh": num(r[2]) if age < 300 else None, "age_s": int(age)}

    # 雷达:JSON 过期或缺值 → None,页面显示 "—",不显示旧值
    radar = {"present": None, "resp_bpm": None, "hr_bpm": None,
             "distance_cm": None, "quality": "NONE"}
    try:
        with open(CFG.radar_state) as f:
            j = json.load(f)
        if now - ts_epoch(j.get("ts", "")) < RADAR_STALE_S:
            radar.update(resp_bpm=j.get("breath_bpm"), hr_bpm=j.get("heart_bpm"),
                         distance_cm=j.get("distance_cm"),
                         present=j.get("distance_cm") is not None)
            radar["quality"] = "MED" if radar["resp_bpm"] else "LOW"
    except (FileNotFoundError, ValueError):
        pass

    # 今日统计 + 24h 分布
    hourly_act = [0] * 24
    hourly_wheel = [0.0] * 24
    act_today = [r for r in act if r[0].startswith(today)]
    for r in act_today:
        hourly_act[int(r[0][11:13])] += 1
    wheel_today = [r for r in wheel if r[0].startswith(today)]
    wheel_sec = 0.0
    for r in wheel_today:
        d = num(r[1]) or 0.0
        wheel_sec += d
        hourly_wheel[int(r[0][11:13])] += d

    last_act = ts_epoch(act[-1][0]) if act else 0
    last_wheel_end = max((ts_epoch(r[0]) + (num(r[1]) or 0) for r in wheel[-5:]), default=0)

    if now - last_wheel_end < WHEEL_RECENT_S:
        st, label, emoji = "VISIBLE_ACTIVE", "On the wheel", "🏃"
    elif now - last_act < ACTIVE_RECENT_S:
        st, label, emoji = "VISIBLE_ACTIVE", "Moving around", "🐾"
    elif last_act:
        st, label, emoji = "VISIBLE_RESTING", "Resting", "🌙"
    else:
        st, label, emoji = "UNKNOWN", "No data yet", "❓"
    since = int(now - max(last_act, last_wheel_end)) if (last_act or last_wheel_end) else None

    return {
        "ts": int(now),
        "state": st, "label": label, "emoji": emoji, "quiet_for_s": since,
        "cam": {"night": is_night(CFG.night_start, CFG.night_end)},
        "radar": radar,
        "env": env_out,
        "today": {"active_events": len(act_today), "wheel_s": int(wheel_sec),
                  "wheel_bouts": len(wheel_today),
                  "hourly_active": hourly_act, "hourly_wheel_s": [int(x) for x in hourly_wheel]},
    }


PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HamiCam</title><style>
:root{--bg:#1c1a17;--card:#2a2621;--fg:#f4ecdf;--mut:#a8998a;--acc:#e8c9a0;--teal:#7fd0c8;--pink:#f5a3b0;--wheel:#f2b84c}
*{box-sizing:border-box}html,body{overflow-x:hidden}body{margin:0;background:var(--bg);color:var(--fg);
font-family:-apple-system,"SF Pro Rounded",Nunito,system-ui,sans-serif;max-width:520px;margin:auto;padding:14px 16px 28px}
.top{display:flex;justify-content:space-between;align-items:center}h1{font-size:20px;margin:6px 0}
.pill{background:var(--card);border-radius:999px;padding:6px 12px;font-size:13px;color:var(--acc)}
.video{position:relative;margin-top:10px;border-radius:18px;overflow:hidden;background:#111;aspect-ratio:16/9}
.video img{width:100%;height:100%;object-fit:cover;display:block}
.tag{position:absolute;top:8px;left:8px;font-size:12px;background:#0009;padding:3px 8px;border-radius:8px}
.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}
.card{background:var(--card);border-radius:16px;padding:12px 10px;min-width:0;overflow-wrap:anywhere}.l{font-size:11px;color:var(--mut)}
.v{font-size:26px;font-weight:700;margin-top:4px}.u{font-size:11px;color:var(--mut)}.dim .v{color:var(--mut)}
.exp{font-size:9px;border:1px solid var(--mut);border-radius:4px;padding:0 3px}
.status{margin-top:12px;background:var(--card);border-radius:16px;padding:14px;display:flex;gap:12px;align-items:center}
.status b{display:block;font-size:15px}.status span{font-size:12px;color:var(--mut)}
h2{font-size:15px;margin:18px 0 8px}.row{display:flex;justify-content:space-between;align-items:center;background:var(--card);
border-radius:14px;padding:12px 14px;margin-bottom:8px;font-size:14px}
.hours{display:flex;align-items:flex-end;gap:2px;height:70px;background:var(--card);border-radius:14px;padding:10px}
.hours div{flex:1;display:flex;flex-direction:column;justify-content:flex-end;height:100%}
.hours i{display:block;border-radius:2px}.lg{font-size:11px;color:var(--mut);margin-top:6px}
.lg i{display:inline-block;width:9px;height:9px;border-radius:2px;margin:0 4px 0 10px}
a{color:var(--acc)}
</style></head><body>
<div class="top"><h1>🐹 HamiCam</h1><div class="pill" id="pill">…</div></div>
<div class="video"><img id="vid" alt="" onerror="this.style.visibility='hidden'"><div class="tag" id="tag">● LIVE</div></div>
<div class="cards">
 <div class="card" id="c-br"><div class="l">〰 Breathing</div><div class="v">—</div><div class="u">radar not connected</div></div>
 <div class="card" id="c-hr"><div class="l">💗 Heart <span class="exp">EXP</span></div><div class="v">—</div><div class="u">radar not connected</div></div>
 <div class="card" id="c-t"><div class="l">🌡 Temp</div><div class="v">—</div><div class="u">sensor offline</div></div>
</div>
<div class="status"><span id="se" style="font-size:26px">❓</span><div><b id="sl">…</b><span id="ss"></span></div></div>
<h2>Today</h2>
<div class="row"><span>🏃 Wheel</span><b id="tw">—</b></div>
<div class="row"><span>🐾 Active events</span><b id="ta">—</b></div>
<div class="hours" id="hours"></div>
<div class="lg"><i style="background:var(--wheel)"></i>wheel<i style="background:var(--teal)"></i>activity · 0–23 h</div>
<p class="lg" style="margin-top:14px"><a id="lnk-act">activity log</a> · <a id="lnk-wheel">wheel stats</a> · <a href="/api/state">api</a></p>
<script>
const H=location.hostname;
document.getElementById('vid').src='http://'+H+':8000/stream';
document.getElementById('lnk-act').href='http://'+H+':8000/activity';
document.getElementById('lnk-wheel').href='http://'+H+':8090/';
const $=id=>document.getElementById(id);
function fmt(s){if(s==null)return'';s=Math.max(0,s|0);const h=s/3600|0,m=(s%3600)/60|0;return h?h+' h '+m+' min':m+' min'}
function card(id,v,u){const c=$(id);c.querySelector('.v').textContent=v==null?'—':v;c.querySelector('.u').textContent=u;c.classList.toggle('dim',v==null)}
async function tick(){
 let s;try{s=await (await fetch('/api/state')).json()}catch(e){$('pill').textContent='offline';return}
 $('pill').textContent=s.emoji+' '+s.label;$('se').textContent=s.emoji;$('sl').textContent=s.label;
 $('ss').textContent=s.quiet_for_s==null?'':(s.state==='VISIBLE_RESTING'?'quiet for '+fmt(s.quiet_for_s):'last seen '+fmt(s.quiet_for_s)+' ago');
 $('tag').textContent='● LIVE'+(s.cam.night?' · 🌙 night':'');
 const r=s.radar,rc=r.quality!=='NONE';
 card('c-br',r.resp_bpm,rc?(r.resp_bpm==null?'signal weak':'breaths/min'):'radar not connected');
 card('c-hr',r.hr_bpm,rc?(r.hr_bpm==null?'needs high signal':'bpm'):'radar not connected');
 card('c-t',s.env.t_c==null?null:s.env.t_c.toFixed(1),s.env.t_c==null?'sensor offline':'°C · '+Math.round(s.env.rh)+'% RH');
 $('tw').textContent=fmt(s.today.wheel_s)+' · '+s.today.wheel_bouts+' bouts';$('ta').textContent=s.today.active_events;
 const mw=Math.max(60,...s.today.hourly_wheel_s),ma=Math.max(3,...s.today.hourly_active);
 $('hours').innerHTML=s.today.hourly_wheel_s.map((w,i)=>'<div><i style="height:'+(w/mw*50)+'%;background:var(--wheel)"></i><i style="height:'+(s.today.hourly_active[i]/ma*50)+'%;background:var(--teal)"></i></div>').join('');
}
tick();setInterval(tick,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        elif self.path == "/api/state":
            self._send(200, "application/json", json.dumps(state(), ensure_ascii=False).encode("utf-8"))
        else:
            self.send_error(404)

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    global CFG
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", type=int, default=8080)
    ap.add_argument("--activity-log", default="/home/pi/hamster_activity.csv")
    ap.add_argument("--wheel-log", default="/home/pi/hamster_wheel.csv")
    ap.add_argument("--env-log", default="/home/pi/hamster_env.csv")
    ap.add_argument("--radar-state", default="/home/pi/hamster_radar.json")
    ap.add_argument("--night-start", type=int, default=20)
    ap.add_argument("--night-end", type=int, default=8)
    CFG = ap.parse_args()
    print("HamiCam 总览: http://<host>:%d/" % CFG.port)
    ThreadingHTTPServer(("0.0.0.0", CFG.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
