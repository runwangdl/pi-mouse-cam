#!/usr/bin/env python3
"""
跑轮声音检测器 (hamster wheel-sound monitor) —— 窄带频谱版
============================================================
仓鼠跑轮虽然总音量小(RMS 抓不到),但在某个窄频段(实测 ~398Hz)有极强单音。
本脚本盯这个频段的能量来判断"在不在跑轮"——黑暗、静音轮都管用。
- arecord 采音 → 每 0.25s 做 FFT → 算 [flo,fhi] 频段能量 → 超阈=活动
- 记时间到 CSV;夜间活动 → 从本地视频流抓一帧,ntfy 推送(声音+照片)
依赖:arecord + numpy(已随 opencv 装),纯标准库其余。
"""
import argparse, subprocess, struct, time, csv, urllib.request
import numpy as np

def now(): return time.strftime("%Y-%m-%d %H:%M:%S")
def is_night(a, b):
    h = int(time.strftime("%H")); return (a <= h < b) if a <= b else (h >= a or h < b)

def grab_frame(url):
    try:
        r = urllib.request.urlopen(url, timeout=5); buf = b""
        for _ in range(200):
            ch = r.read(8192)
            if not ch: break
            buf += ch
            s = buf.find(b"\xff\xd8"); e = buf.find(b"\xff\xd9", s + 2)
            if s != -1 and e != -1: return buf[s:e + 2]
    except Exception: pass
    return None

def ntfy_push(topic, title, msg, jpg=None):
    if not topic: return
    try:
        h = {"Title": title.encode("utf-8"), "Tags": "wheel,hamster"}
        data = jpg if jpg is not None else msg.encode("utf-8")
        if jpg is not None: h["Filename"] = "hamster.jpg"
        urllib.request.urlopen(urllib.request.Request(
            "https://ntfy.sh/" + topic, data=data, headers=h, method="POST"), timeout=8)
    except Exception: pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="plughw:1,0")
    ap.add_argument("--rate", type=int, default=16000)
    ap.add_argument("--win", type=float, default=0.25)
    ap.add_argument("--flo", type=float, default=380, help="跑轮频段下限 Hz")
    ap.add_argument("--fhi", type=float, default=410, help="跑轮频段上限 Hz")
    ap.add_argument("--thresh", type=float, default=8000, help="频段能量阈值")
    ap.add_argument("--min-win", type=int, default=2)
    ap.add_argument("--cooldown", type=float, default=300)
    ap.add_argument("--night-start", type=int, default=20)
    ap.add_argument("--night-end", type=int, default=8)
    ap.add_argument("--ntfy", default="")
    ap.add_argument("--stream", default="http://127.0.0.1:8000/stream")
    ap.add_argument("--log", default="/home/pi/hamster_wheel.csv")
    ap.add_argument("--verbose", action="store_true")
    cfg = ap.parse_args()

    winlen = int(cfg.rate * cfg.win); nbytes = winlen * 2
    han = np.hanning(winlen)
    freqs = np.fft.rfftfreq(winlen, 1.0 / cfg.rate)
    band = (freqs >= cfg.flo) & (freqs < cfg.fhi)

    proc = subprocess.Popen(
        ["arecord", "-D", cfg.device, "-f", "S16_LE", "-r", str(cfg.rate),
         "-c", "1", "-t", "raw", "-q"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    run = 0; quiet = 0; last_notify = 0.0; bout = False; tick = 0
    t_start = 0.0; max_e = 0.0; b_night = False; b_ts = ""
    end_win = int(2.0 / cfg.win)          # 连续静 2s 才算这段跑轮结束(容忍短暂停顿)
    print("跑轮声音监控中: %g-%gHz 阈值%g 夜间%d-%d ntfy=%s"
          % (cfg.flo, cfg.fhi, cfg.thresh, cfg.night_start, cfg.night_end, cfg.ntfy or "关"))
    while True:
        raw = proc.stdout.read(nbytes)
        if len(raw) < nbytes: time.sleep(0.1); continue
        s = np.array(struct.unpack("<%dh" % winlen, raw), dtype=float) * han
        S = np.abs(np.fft.rfft(s))
        energy = float(np.sqrt(np.mean(S[band] ** 2)))
        wheel = energy > cfg.thresh
        tick += 1
        if cfg.verbose and tick % 4 == 0:
            print("%s  band=%.0f %s" % (time.strftime("%H:%M:%S"), energy, "🎡" if wheel else ""))

        if wheel:
            run += 1; quiet = 0
            if not bout and run >= cfg.min_win:
                bout = True; t_start = time.time(); b_ts = now(); max_e = energy
                b_night = is_night(cfg.night_start, cfg.night_end)
                print("%s  🎡 开始跑轮  band=%.0f  %s" % (b_ts, energy, "NIGHT" if b_night else ""))
                if b_night and (time.time() - last_notify) > cfg.cooldown:
                    last_notify = time.time()
                    ntfy_push(cfg.ntfy, "🐹🎡 仓鼠在跑轮 %s" % b_ts,
                              "wheel band=%.0f" % energy, grab_frame(cfg.stream))
            elif bout:
                max_e = max(max_e, energy)
        else:
            run = 0
            if bout:
                quiet += 1
                if quiet >= end_win:              # 这段跑轮结束 → 记时长
                    dur = time.time() - t_start - end_win * cfg.win
                    with open(cfg.log, "a", newline="") as f:
                        csv.writer(f).writerow([b_ts, "%.0f" % max(dur, 0),
                                                "%.0f" % max_e, "night" if b_night else "day"])
                    print("%s  ⏹ 跑轮结束  时长=%.0fs" % (now(), max(dur, 0)))
                    bout = False; quiet = 0

if __name__ == "__main__":
    main()
