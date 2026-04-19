"""
system_monitor.py — Background thread that polls CPU, RAM, temp, network stats.
"""

import datetime
import logging
import socket
import subprocess
import threading
import time

import psutil

from shared_state import _system_stats, _stats_lock

logger = logging.getLogger("kida.monitor")


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "N/A"


def _stats_worker() -> None:
    while True:
        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            dio = psutil.disk_io_counters()
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp = int(f.read()) / 1000.0
            try:
                out  = subprocess.check_output(
                    ["ping", "-c", "1", "-W", "1", "8.8.8.8"], timeout=1.5
                ).decode()
                line = next((l for l in out.splitlines() if "time=" in l), "")
                lat  = line.split("time=")[1].split()[0] + " ms" if line else "N/A"
            except Exception:
                lat = "N/A"

            with _stats_lock:
                _system_stats.update({
                    "cpu":        cpu,
                    "temp":       temp,
                    "ram_used":   mem.used  // (1024 * 1024),
                    "ram_total":  mem.total // (1024 * 1024),
                    "ip":         get_local_ip(),
                    "disk_read":  round(dio.read_bytes  / 1024 / 1024, 1),
                    "disk_write": round(dio.write_bytes / 1024 / 1024, 1),
                    "boot_time":  datetime.datetime.fromtimestamp(
                                      psutil.boot_time()).strftime("%H:%M %d/%m"),
                    "latency":    lat,
                    "threads":    threading.active_count(),
                })
        except Exception as e:
            logger.warning("Stats error: %s", e)
        time.sleep(2)


def start_stats_thread() -> threading.Thread:
    t = threading.Thread(target=_stats_worker, daemon=True)
    t.start()
    return t
