#!/usr/bin/env python3
"""
60 GHz 雷达读取 (Seeed MR60BHA2, UART) —— 呼吸率 / 心率 / 距离
===============================================================
⚠ 帧格式按 Seeed 开源 Arduino 库 (Seeed_Arduino_mmWave) 的 TinyFrame 协议写,
  还没有在实物上验证。到货后先跑  --dump  看原始帧,不对再改 TYPE_* 常量。
⚠ MR60BHA2 出厂是和 XIAO ESP32C6 装在一起的套件,雷达 UART 连在 XIAO 上。
  接树莓派两种办法: (a) 拔掉 XIAO,从排针引出雷达 TX/RX/5V/GND;
  (b) 保留 XIAO,刷一个透传固件把雷达 UART 转发到 USB 串口,Pi 读 /dev/ttyACM0。

帧: SOF(0x01) | ID u16 | LEN u16 | TYPE u16 | HEAD_CKSUM | DATA[LEN] | DATA_CKSUM
    头部 u16 为大端;DATA 内 float/u32 为小端;CKSUM = ~(逐字节 XOR)
接线 (方案 a): 雷达 TX→GPIO15 (RXD, pin 10), 雷达 RX→GPIO14 (TXD, pin 8), 5V, GND
先 raspi-config 关掉串口登录、打开串口硬件: 设备 /dev/serial0

输出: 每秒一行 CSV  ts, breath_bpm, heart_bpm, distance_cm
      并把最新值写到 --state (JSON),给总览页用。
纯标准库(termios),不需要 pyserial。
"""
import argparse, csv, json, os, struct, termios, time

TYPE_PHASE = 0x0A13
TYPE_BREATH = 0x0A14
TYPE_HEART = 0x0A15
TYPE_DISTANCE = 0x0A16


def cksum(b):
    x = 0
    for v in b:
        x ^= v
    return (~x) & 0xFF


def open_serial(dev, baud):
    fd = os.open(dev, os.O_RDONLY | os.O_NOCTTY)
    attr = termios.tcgetattr(fd)
    speed = getattr(termios, "B%d" % baud)
    attr[0] = 0                                   # iflag
    attr[1] = 0                                   # oflag
    attr[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attr[3] = 0                                   # lflag (raw)
    attr[4] = attr[5] = speed
    attr[6][termios.VMIN] = 1
    attr[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attr)
    return fd


class Parser:
    """流式切帧,喂任意字节块,吐出 (type, data)。"""

    def __init__(self):
        self.buf = bytearray()
        self.bad = 0

    def feed(self, chunk):
        self.buf += chunk
        out = []
        while True:
            i = self.buf.find(b"\x01")
            if i < 0:
                self.buf.clear(); break
            del self.buf[:i]
            if len(self.buf) < 8:
                break
            _id, ln, typ = struct.unpack(">HHH", self.buf[1:7])
            if cksum(self.buf[:7]) != self.buf[7] or ln > 256:
                self.bad += 1; del self.buf[:1]; continue
            end = 8 + ln + (1 if ln else 0)
            if len(self.buf) < end:
                break
            data = bytes(self.buf[8:8 + ln])
            if ln and cksum(data) != self.buf[8 + ln]:
                self.bad += 1; del self.buf[:1]; continue
            out.append((typ, data))
            del self.buf[:end]
        return out


def decode(typ, data, st):
    if typ == TYPE_BREATH and len(data) >= 4:
        st["breath_bpm"] = round(struct.unpack("<f", data[:4])[0], 1)
    elif typ == TYPE_HEART and len(data) >= 4:
        st["heart_bpm"] = round(struct.unpack("<f", data[:4])[0], 1)
    elif typ == TYPE_DISTANCE and len(data) >= 8:
        flag, rng = struct.unpack("<If", data[:8])
        st["distance_cm"] = round(rng * 100, 1) if flag else None


def build_frame(typ, data, fid=0):
    """测试用:按同一协议组一帧。"""
    head = b"\x01" + struct.pack(">HHH", fid, len(data), typ)
    return head + bytes([cksum(head)]) + data + (bytes([cksum(data)]) if data else b"")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--log", default="/home/pi/hamster_radar.csv")
    ap.add_argument("--state", default="/home/pi/hamster_radar.json")
    ap.add_argument("--dump", action="store_true", help="打印每一帧 type/hex,调协议用")
    cfg = ap.parse_args()

    fd = open_serial(cfg.dev, cfg.baud)
    p = Parser()
    st = {"breath_bpm": None, "heart_bpm": None, "distance_cm": None}
    last = 0.0
    print("雷达读取中 %s @%d → %s" % (cfg.dev, cfg.baud, cfg.log))
    while True:
        for typ, data in p.feed(os.read(fd, 256)):
            if cfg.dump:
                print("type=0x%04X len=%d %s" % (typ, len(data), data.hex()))
            decode(typ, data, st)
        if time.time() - last >= 1.0:
            last = time.time()
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(cfg.log, "a", newline="") as f:
                csv.writer(f).writerow([ts, st["breath_bpm"], st["heart_bpm"], st["distance_cm"]])
            tmp = cfg.state + ".tmp"
            with open(tmp, "w") as f:
                json.dump(dict(st, ts=ts, bad_frames=p.bad), f)
            os.replace(tmp, cfg.state)


if __name__ == "__main__":
    main()
