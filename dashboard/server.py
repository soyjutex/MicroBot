#!/usr/bin/env python3
"""
MicroBot Dashboard - servidor web de solo lectura.

Sirve dashboard.html y expone dos endpoints JSON con datos REALES:
    /api/stats -> CPU/RAM/disco/temperatura leidos de /proc y /sys en vivo
    /api/bot   -> conteos de memoria SQLite + ultimos hechos/errores + cola del log

Sin dependencias externas: solo stdlib. Puerto 8080.
"""

import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("MICROBOT_DASH_PORT", "8080"))
BASE = os.path.dirname(os.path.abspath(__file__))
DB = "/opt/microbot/data/microbot.db"
LOG = "/opt/microbot/data/microbot.log"


def sys_stats():
    out = {"cpu": None, "ram": None, "disk": None, "temp": None}
    try:
        out["cpu"] = min(round(os.getloadavg()[0] * 100 / os.cpu_count(), 1), 100)
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            mi = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    mi[parts[0]] = int(parts[1].split()[0])
        total = mi.get("MemTotal", 0) or 1
        available = mi.get("MemAvailable", 0)
        out["ram"] = round((total - available) * 100 / total, 1)
    except Exception:
        pass
    try:
        st = os.statvfs("/")
        out["disk"] = round((st.f_blocks - st.f_bfree) * 100 / st.f_blocks, 1)
    except Exception:
        pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            out["temp"] = round(int(f.read()) / 1000, 1)
    except Exception:
        pass
    return out


def bot_data():
    data = {
        "facts": 0, "history": 0, "errors": 0, "skills": 0,
        "recent_facts": [], "recent_errors": [],
    }
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        cur = con.cursor()
        for table in ("facts", "history", "errors", "skills"):
            data[table] = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        data["recent_facts"] = [
            {"ts": r[0], "text": r[1]}
            for r in cur.execute("SELECT ts, text FROM facts ORDER BY id DESC LIMIT 8")
        ]
        data["recent_errors"] = [
            {"ts": r[0], "ctx": r[1], "err": r[2]}
            for r in cur.execute("SELECT ts, ctx, err FROM errors ORDER BY id DESC LIMIT 5")
        ]
        con.close()
    except Exception:
        pass
    return data


def tail_log(lines=15):
    try:
        with open(LOG, errors="replace") as f:
            return f.readlines()[-lines:]
    except Exception:
        return []


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/stats":
            self._send(200, json.dumps(sys_stats()).encode())
        elif self.path == "/api/bot":
            data = bot_data()
            data["log"] = tail_log()
            self._send(200, json.dumps(data).encode())
        elif self.path in ("/", "/index.html"):
            try:
                with open(os.path.join(BASE, "dashboard.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except Exception:
                self.send_error(404)
        else:
            self.send_error(404)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    print(f"MicroBot dashboard en http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
