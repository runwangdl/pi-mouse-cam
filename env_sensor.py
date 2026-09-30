#!/usr/bin/env python3
"""
温湿度记录 (AHT20 over I2C) —— 纯标准库,不需要 smbus2
=========================================================
接线: AHT20 VIN→3V3, GND→GND, SDA→GPIO2 (pin 3), SCL→GPIO3 (pin 5)
先在 raspi-config 里打开 I2C,  `ls /dev/i2c-1` 应存在。
每 --interval 秒读一次,追加到 CSV: ts, temp_c, rh
用 --fake 在没有传感器的机器上生成假数据(调页面用)。
"""
import argparse, csv, fcntl, os, random, time

I2C_SLAVE = 0x0703
ADDR = 0x38


class AHT20:
    def __init__(self, bus=1):
        self.fd = os.open("/dev/i2c-%d" % bus, os.O_RDWR)
        fcntl.ioctl(self.fd, I2C_SLAVE, ADDR)
        time.sleep(0.04)
        os.write(self.fd, bytes([0x71]))
        if not (os.read(self.fd, 1)[0] & 0x08):          # 未校准 → 初始化
            os.write(self.fd, bytes([0xBE, 0x08, 0x00]))
            time.sleep(0.01)

    def read(self):
        os.write(self.fd, bytes([0xAC, 0x33, 0x00]))
        time.sleep(0.08)
        for _ in range(5):
            d = os.read(self.fd, 7)
            if not (d[0] & 0x80):                        # busy 位清零
                break
            time.sleep(0.02)
        rh_raw = (d[1] << 12) | (d[2] << 4) | (d[3] >> 4)
        t_raw = ((d[3] & 0x0F) << 16) | (d[4] << 8) | d[5]
        return t_raw * 200.0 / (1 << 20) - 50.0, rh_raw * 100.0 / (1 << 20)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bus", type=int, default=1)
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--log", default="/home/pi/hamster_env.csv")
    ap.add_argument("--fake", action="store_true", help="无传感器,生成假数据")
    cfg = ap.parse_args()

    sensor = None if cfg.fake else AHT20(cfg.bus)
    print("温湿度记录中 → %s (每 %gs)%s" % (cfg.log, cfg.interval, " [FAKE]" if cfg.fake else ""))
    while True:
        try:
            if sensor:
                t, rh = sensor.read()
            else:
                t, rh = 22.5 + random.uniform(-0.8, 0.8), 48 + random.uniform(-4, 4)
            with open(cfg.log, "a", newline="") as f:
                csv.writer(f).writerow([time.strftime("%Y-%m-%d %H:%M:%S"),
                                        "%.2f" % t, "%.1f" % rh])
        except OSError as e:
            print("读取失败:", e)
        time.sleep(cfg.interval)


if __name__ == "__main__":
    main()
