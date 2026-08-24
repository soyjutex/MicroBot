#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MicroBot v8.0 UNIVERSAL - Agente autonomo multiplataforma (Linux / macOS / Windows).

UN solo archivo con TODAS las capacidades, para CUALQUIER OS. La Capa de
Abstraccion de Plataforma (PAL) detecta el sistema al arrancar y conecta
telemetria, shell y lock nativos. El resto del cerebro es identico en todas
las plataformas: misiones, critic, skills, compresion nocturna, outbox,
pipeline visible y presupuesto cerrado.

Caracteristicas principales:
    - Cerebro LLM agnostico (OpenRouter/Groq/Gemini/Ollama) con protocolo JSON estricto: piensa, planifica, ejecuta, critica y aprende.
    - Memoria semantica: SQLite + FTS5 inyecta solo los hechos relevantes a cada mensaje (zero-token bloat).
    - Busqueda web quirurgica opcional y compresion nocturna de memoria a las 04:00.
    - Misiones multi-paso, critic loop, skills Python validadas, circuit breaker.
    - Pipeline visible: burbuja de tipeo + mensaje de estado que se edita por capa real.
    - Outbox: si la red falla, las respuestas se entregan al volver la conexion.
    - Memoria persistente unificada en SQLite (facts, historial, errores, misiones, skills).
    - Presupuesto diario de llamadas API + circuit breaker anti-cascada de errores.
    - Consciencia de hardware: auto-pausa si la RAM o la CPU estan en limites.

Seguridad:
    - Las credenciales viven en config.json (chmod 600), NUNCA en el codigo.
    - Lista BLOCKED por OS: comandos destructivos rechazados antes de ejecutarse.
    - Un solo chat de Telegram autorizado.

Estructura del archivo (busca los marcadores "=== SECCION ==="):
    1. Imports y carga de configuracion
    2. Logging
    3. Almacenamiento (SQLite)
    4. Estadisticas de sistema
    5. Ejecucion de comandos
    6. Telegram
    7. Cliente LLM
    8. Skills
    9. Gestion de turnos (con multi-respuesta)
    10. Misiones
    11. Comandos locales (slash-commands)
    12. Daemons (Telegram + auto-ciclos)
    13. CLI y punto de entrada
"""

import ast
import datetime
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

if platform.system() == "Windows":
    import msvcrt
else:
    import fcntl

import requests

# ==============================================================================
# === 1. IMPORTS Y CARGA DE CONFIGURACION =====================================
# ==============================================================================

BASE_DIR = os.path.dirname(os.path.realpath(__file__))   # realpath: resuelve symlinks del CLI global
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.environ.get("MICROBOT_CONFIG", os.path.join(BASE_DIR, "config.json"))
DB_FILE = os.path.join(DATA_DIR, "microbot.db")

DEFAULTS = {
    "api_key": "",
    "provider": "openrouter",          # openrouter (gratis) | gemini
    "model": "openrouter/free",        # router automatico de modelos gratis de OpenRouter
    "base_url": "https://openrouter.ai/api/v1",   # cualquier API compatible OpenAI (Groq, Ollama local, vLLM...)
    "telegram_token": "",
    "chat_id": "",
    "max_calls_per_day": 45,           # techo conservador: el tier free de OpenRouter da ~50/dia
    "max_auto_cycles_per_day": 6,
    "auto_interval_sec": 1800,
    "cmd_timeout_sec": 60,
    "error_threshold": 0.5,
    "min_errors_for_breaker": 3,
    "backoff_base_sec": 3600,
    "mission_max_steps": 6,
    "ram_min_mb": 150,
    "load_max": 4.0,
    "cpu_max_pct": 85,                 # usado en Windows/macOS donde no hay loadavg
    "max_alternatives": 2,
}


def load_config():
    """Carga la configuracion desde JSON. Permite override por variables de entorno MICROBOT_*."""
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"[CONFIG] Error leyendo {CONFIG_FILE}: {e}. Uso defaults.", file=sys.stderr)
    # Override por entorno (util en CI o sin archivo)
    for key in list(cfg.keys()):
        env_val = os.environ.get(f"MICROBOT_{key.upper()}")
        if env_val is not None:
            cfg[key] = env_val
    return cfg


CFG = load_config()

store_global = None   # referencia global al Store activo (para tg_send/outbox)


def now_iso():
    """Timestamp ISO local, usado en toda la memoria."""
    return datetime.datetime.now().isoformat()


PID_FILE = os.path.join(DATA_DIR, "microbot.pid")
SELF_FILE = os.path.abspath(__file__)

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# Comandos que MicroBot nunca ejecuta, ni siquiera como root.
BLOCKED_UNIX = [
    r"rm\s+-[rf]{1,2}\s*/(?:\s|$)",    # rm -rf /  (con o sin flag invertida)
    r"--no-preserve-root",
    r"mkfs",
    r"dd\s+if=",
    r":\(\)\s*\{\s*:\|\:&\s*;\s*\}",   # fork bomb
    r"shutdown",
    r"reboot",
    r"halt",
    r">\s*/dev/sd",
    r"chmod\s+-R\s+777\s+/\b",
]
BLOCKED_WINDOWS = [
    r"format\s+[a-z]:",
    r"\bdiskpart\b",
    r"Remove-Item\s+[^|]*-[Rr]ecurse[^|]*-\s*[Ff]orce\s+[\"']?[a-zA-Z]:\\\s*\"?'?$",
    r"\brd\s+/s\s+/q\s+[a-z]:\\\s*$",
    r"\bdel\s+/[sf]\b.*[c-z]:\\\s*$",
    r"\bshutdown\b",
    r"\bbcdedit\b",
    r"reg\s+delete\s+HKLM",
    r"\bcipher\s+/w\b",
]
BLOCKED = BLOCKED_WINDOWS if IS_WINDOWS else BLOCKED_UNIX

# ==============================================================================
# === 2. LOGGING ===============================================================
# ==============================================================================

os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(os.path.join(DATA_DIR, "microbot.log")), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("microbot")
executor = ThreadPoolExecutor(max_workers=1)


# ==============================================================================
# === 3. ALMACENAMIENTO (SQLITE UNIFICADO) ====================================
# ==============================================================================

class Store:
    """Memoria persistente unificada. Toda la informacion vive aqui, en SQLite."""

    def __init__(self, path):
        self.conn = sqlite3_connect(path)
        self._init_schema()
        global store_global
        store_global = self

    def _init_schema(self):
        c = self.conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                text TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                user TEXT NOT NULL,
                assistant TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                ctx TEXT NOT NULL,
                err TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS missions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                goal TEXT NOT NULL,
                steps INTEGER DEFAULT 0,
                state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scratchpad (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                label TEXT,
                cmd TEXT,
                out TEXT);
            CREATE TABLE IF NOT EXISTS skills (
                name TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                desc TEXT DEFAULT '',
                created TEXT NOT NULL);
        """)
        self.conn.commit()
        # FTS5 (full-text search) para recuperacion semantica ligera de hechos.
        # Si la build de SQLite no trae FTS5, se degrada a LIKE sin romper nada.
        self.has_fts = False
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(ts, text)")
            self.conn.commit()
            n_fts = c.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0]
            if n_fts != c.execute("SELECT COUNT(*) FROM facts").fetchone()[0]:
                c.execute("INSERT INTO facts_fts (ts, text) SELECT ts, text FROM facts")
                self.conn.commit()
            self.has_fts = True
        except Exception:
            pass

    # --- clave/valor (estado simple: usage, auto, breaker...) ---------------
    def get(self, key, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        self.conn.commit()

    # --- facts ---------------------------------------------------------------
    STOPWORDS = frozenset(
        "de la el los las un una unos unas y o a en que al del lo se su por para con sin sobre "
        "es son esta estan fue ser soy estoy me mi mis tu tus le les lo hay aqui ahi the and for "
        "with this that what when where how your you are was were have has had not but all can "
        "cual cuales como cuando donde quien cuanto decime deci hace hacer quiero quiero podes".split()
    )

    def add_fact(self, text):
        ts = now_iso()
        self.conn.execute("INSERT INTO facts (ts, text) VALUES (?, ?)", (ts, text[:500]))
        if self.has_fts:
            try:
                self.conn.execute("INSERT INTO facts_fts (ts, text) VALUES (?, ?)", (ts, text[:500]))
            except Exception:
                pass
        self.conn.commit()

    def facts(self, limit=15):
        rows = self.conn.execute("SELECT text FROM facts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [r[0] for r in reversed(rows)]

    def all_facts(self, limit=120):
        rows = self.conn.execute("SELECT id, ts, text FROM facts ORDER BY id ASC LIMIT ?", (limit,)).fetchall()
        return rows

    def replace_facts(self, new_texts):
        """Reemplaza TODOS los hechos (usado por la compresion nocturna)."""
        c = self.conn.cursor()
        c.execute("DELETE FROM facts")
        if self.has_fts:
            try:
                c.execute("DELETE FROM facts_fts")
            except Exception:
                pass
        for t in new_texts:
            ts = now_iso()
            c.execute("INSERT INTO facts (ts, text) VALUES (?, ?)", (ts, t[:500]))
            if self.has_fts:
                try:
                    c.execute("INSERT INTO facts_fts (ts, text) VALUES (?, ?)", (ts, t[:500]))
                except Exception:
                    pass
        self.conn.commit()

    @staticmethod
    def _keywords(text, max_kw=6):
        kws = [w for w in re.findall(r"[a-z0-9]{4,}", str(text).lower())
               if w not in Store.STOPWORDS]
        return kws[:max_kw]

    def relevant_facts(self, query, limit=5):
        """Recuperacion semantica ligera: solo los hechos relevantes al mensaje.
        Cero tokens de mas: FTS5 con MATCH si esta disponible, LIKE como fallback,
        y solo como ultima opcion los hechos recientes."""
        kws = self._keywords(query)
        if not kws:
            return self.facts(limit)
        if self.has_fts:
            try:
                match = " OR ".join('"' + k.replace('"', '""') + '"' for k in kws)
                rows = self.conn.execute(
                    "SELECT text FROM facts_fts WHERE facts_fts MATCH ? ORDER BY rank LIMIT ?",
                    (match, limit)).fetchall()
                if rows:
                    return [r[0] for r in rows]
            except Exception:
                pass
        like = " OR ".join(["text LIKE ?"] * len(kws))
        params = [f"%{k}%" for k in kws]
        rows = self.conn.execute(
            f"SELECT text FROM facts WHERE {like} ORDER BY id DESC LIMIT ?", params + [limit]).fetchall()
        return [r[0] for r in rows] if rows else self.facts(limit)

    def count_facts(self):
        return self.conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    # --- history -------------------------------------------------------------
    def add_history(self, user, assistant):
        self.conn.execute("INSERT INTO history (ts, user, assistant) VALUES (?, ?, ?)",
                          (now_iso(), str(user)[:500], str(assistant)[:500]))
        self.conn.commit()
        # Rotacion: conservar solo los ultimos 40 turnos
        self.conn.execute("""DELETE FROM history WHERE id NOT IN
                             (SELECT id FROM history ORDER BY id DESC LIMIT 40)""")
        self.conn.commit()

    def recent_history(self, limit=5):
        rows = self.conn.execute("SELECT user, assistant FROM history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"user": u, "assistant": a} for u, a in reversed(rows)]

    # --- errors --------------------------------------------------------------
    def add_error(self, ctx, err):
        self.conn.execute("INSERT INTO errors (ts, ctx, err) VALUES (?, ?, ?)",
                          (now_iso(), str(ctx)[:200], str(err)[:300]))
        self.conn.commit()

    def recent_errors(self, limit=10):
        rows = self.conn.execute(
            "SELECT ts, ctx, err FROM errors ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]   # tuplas planas: JSON-safe

    def error_rate_last_hour(self):
        cutoff = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        total = self.conn.execute("SELECT COUNT(*) FROM errors WHERE ts >= ?", (cutoff,)).fetchone()[0]
        if not total:
            return 0.0
        auto = self.conn.execute(
            "SELECT COUNT(*) FROM errors WHERE ts >= ? AND (ctx LIKE '%auto%' OR ctx LIKE '%mision%')",
            (cutoff,)).fetchone()[0]
        return auto / max(1, total)

    # --- missions ------------------------------------------------------------
    def add_mission(self, goal, steps, state):
        self.conn.execute("INSERT INTO missions (ts, goal, steps, state) VALUES (?, ?, ?, ?)",
                          (now_iso(), goal[:200], steps, state))
        self.conn.commit()

    def recent_missions(self, limit=10):
        rows = self.conn.execute(
            "SELECT ts, goal, steps, state FROM missions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]   # tuplas planas: JSON-safe

    # --- scratchpad ----------------------------------------------------------
    def add_scratch(self, label, cmd, out):
        self.conn.execute("INSERT INTO scratchpad (ts, label, cmd, out) VALUES (?, ?, ?, ?)",
                          (now_iso(), str(label)[:80], str(cmd)[:200], str(out)[:300]))
        self.conn.commit()
        self.conn.execute("""DELETE FROM scratchpad WHERE id NOT IN
                             (SELECT id FROM scratchpad ORDER BY id DESC LIMIT 30)""")
        self.conn.commit()

    def recent_scratch(self, limit=8):
        rows = self.conn.execute(
            "SELECT ts, label, cmd, out FROM scratchpad ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"cmd": c, "out": o} for _, _, c, o in reversed(rows)]

    # --- skills --------------------------------------------------------------
    def save_skill(self, name, code, desc):
        self.conn.execute("INSERT OR REPLACE INTO skills (name, code, desc, created) VALUES (?, ?, ?, ?)",
                          (name, code, desc[:200], now_iso()))
        self.conn.commit()

    def get_skill(self, name):
        row = self.conn.execute("SELECT code, desc FROM skills WHERE name=?", (name,)).fetchone()
        return {"code": row[0], "desc": row[1]} if row else None

    def del_skill(self, name):
        self.conn.execute("DELETE FROM skills WHERE name=?", (name,))
        self.conn.commit()

    def skill_names(self):
        return [r[0] for r in self.conn.execute("SELECT name FROM skills").fetchall()]

    def close(self):
        self.conn.close()


def sqlite3_connect(path):
    import sqlite3
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ==============================================================================
# === 4. ESTADISTICAS DE SISTEMA (PAL) =========================================
# ==============================================================================

def telemetry():
    """Stats reales del sistema sin procesos pesados. Windows: ctypes Win32.
    Linux/macOS: /proc y /sys. Nunca lanza excepciones."""
    out = {"ram_free_mb": None, "ram_total_mb": None, "cpu_pct": None,
           "temp_c": None, "disk_pct": None}
    if IS_WINDOWS:
        try:
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_uint64),
                            ("ullAvailPhys", ctypes.c_uint64),
                            ("ullTotalPageFile", ctypes.c_uint64),
                            ("ullAvailPageFile", ctypes.c_uint64),
                            ("ullTotalVirtual", ctypes.c_uint64),
                            ("ullAvailVirtual", ctypes.c_uint64),
                            ("ullAvailExtendedVirtual", ctypes.c_uint64)]

            st = MemStatus()
            st.dwLength = ctypes.sizeof(MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                out["ram_total_mb"] = st.ullTotalPhys // 1048576
                out["ram_free_mb"] = st.ullAvailPhys // 1048576
        except Exception:
            pass
        try:
            import ctypes

            class FileTime(ctypes.Structure):
                _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

            def ft_value(ft):
                return (ft.hi << 32) + ft.lo

            k32 = ctypes.windll.kernel32
            idle1, kern1, user1 = FileTime(), FileTime(), FileTime()
            k32.GetSystemTimes(ctypes.byref(idle1), ctypes.byref(kern1), ctypes.byref(user1))
            time.sleep(0.25)
            idle2, kern2, user2 = FileTime(), FileTime(), FileTime()
            k32.GetSystemTimes(ctypes.byref(idle2), ctypes.byref(kern2), ctypes.byref(user2))
            total = (ft_value(kern2) - ft_value(kern1)) + (ft_value(user2) - ft_value(user1))
            busy = total - (ft_value(idle2) - ft_value(idle1))
            out["cpu_pct"] = round(busy * 100 / total, 1) if total else None
        except Exception:
            pass
    else:
        try:
            with open("/proc/meminfo") as f:
                mi = {}
                for line in f:
                    k, _, v = line.partition(":")
                    mi[k.strip()] = int(v.strip().split()[0])
            out["ram_total_mb"] = mi.get("MemTotal", 0) // 1024
            out["ram_free_mb"] = mi.get("MemAvailable", 0) // 1024
        except Exception:
            pass
        try:
            load1 = float(open("/proc/loadavg").read().split()[0])
            ncpu = os.cpu_count() or 1
            out["cpu_pct"] = min(round(load1 * 100 / ncpu, 1), 100)
        except Exception:
            pass
        path = None if IS_MAC else "/sys/class/thermal/thermal_zone0/temp"
        try:
            if path and os.path.exists(path):
                out["temp_c"] = round(int(open(path).read().strip()) / 1000, 1)
        except Exception:
            pass
    try:
        disk_root = os.environ.get("SystemDrive", "C:") + "\\" if IS_WINDOWS else DATA_DIR
        st = os.statvfs(disk_root)
        out["disk_pct"] = round((st.f_blocks - st.f_bfree) * 100 / st.f_blocks, 1)
    except Exception:
        pass
    return out


def get_sys_stats():
    """Dict con stats + string resumen (compatible con todo el codigo existente)."""
    t = telemetry()
    load1 = None
    if not IS_WINDOWS:
        try:
            load1 = float(open("/proc/loadavg").read().split()[0])
        except Exception:
            pass
    s = {
        "cpu_pct": t["cpu_pct"],
        "ram_free": t["ram_free_mb"] or 0,
        "ram_total": t["ram_total_mb"] or 0,
        "temp_c": t["temp_c"],
        "disk_pct": t["disk_pct"],
        "load1": load1,
    }
    parts = []
    if t["cpu_pct"] is not None:
        parts.append(f"cpu={t['cpu_pct']}%")
    parts.append(f"ram={s['ram_free']}MB libres de {s['ram_total']}MB")
    if t["temp_c"] is not None:
        parts.append(f"temp={t['temp_c']}C")
    if load1 is not None:
        parts.append(f"load={load1}")
    if t["disk_pct"] is not None:
        parts.append(f"disco={t['disk_pct']}%")
    s["str"] = " ".join(parts) or "stats no disponibles"
    return s


def resources_ok():
    """Guardia de recursos: RAM minima y techo de CPU o load segun plataforma."""
    s = get_sys_stats()
    ram_ok = s["ram_free"] >= CFG["ram_min_mb"]
    if s["cpu_pct"] is not None:
        return ram_ok and s["cpu_pct"] <= CFG["cpu_max_pct"]
    if s["load1"] is not None:
        return ram_ok and s["load1"] <= CFG["load_max"]
    return ram_ok


_HOST_ID = None


def host_identity():
    """Identidad real del equipo: hostname, OS y CPU. Leida en vivo, sin hardcodear."""
    global _HOST_ID
    if _HOST_ID is None:
        host = socket.gethostname()
        os_name = f"{platform.system()} {platform.release()}"
        cpu = platform.processor() or platform.machine()
        _HOST_ID = (host, os_name, cpu)
    return _HOST_ID


# ==============================================================================
# === 5. EJECUCION DE COMANDOS (PAL: bash / PowerShell) ========================
# ==============================================================================

def run_cmd(cmd):
    """Ejecuta un comando en la shell nativa del OS con guarda anti-destructivos."""
    for pat in BLOCKED:
        if re.search(pat, cmd, re.IGNORECASE):
            return "[BLOQUEADO] comando peligroso rechazado"
    try:
        if IS_WINDOWS:
            full = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
        else:
            full = ["bash", "-c", cmd]
        r = subprocess.run(full, capture_output=True, text=True,
                           timeout=CFG["cmd_timeout_sec"],
                           errors="replace",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        return out.strip()[:4000] if out.strip() else "(sin salida)"
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT {CFG['cmd_timeout_sec']}s]"
    except Exception as e:
        return str(e)


# ==============================================================================
# === 6. TELEGRAM =============================================================
# ==============================================================================

def tg_send(text):
    """Envia mensaje al chat autorizado con reintentos y log (nunca tumba el daemon).
    Si la red falla, encola en kv 'outbox' y lo entrega al proximo envio exitoso."""
    for attempt in (1, 2, 3):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{CFG['telegram_token']}/sendMessage",
                json={"chat_id": CFG["chat_id"], "text": text[:4000]},
                timeout=15,
            )
            if r.status_code == 200:
                _flush_outbox()
                return True
            log.warning("tg_send intento %d: HTTP %s %s", attempt, r.status_code, r.text[:120])
        except Exception as e:
            log.warning("tg_send intento %d: %s", attempt, str(e)[:120])
        time.sleep(2 * attempt)
    outbox = store_global.get("outbox", []) if store_global else []
    outbox.append(text[:4000])
    if store_global:
        store_global.set("outbox", outbox[-10:])
    log.error("tg_send FALLO tras reintentos; mensaje encolado (%d)", len(outbox))
    return False


# --- Pipeline visible: burbuja de "escribiendo" + mensaje de estado editable ---
STAGE_MSG = {
    "recv":   "\U0001F4E8 Mensaje recibido - entrando al pipeline...",
    "think":  "\U0001F9E0 Pensando - consultando al modelo...",
    "search": "\U0001F310 Capa web - buscando en internet...",
    "exec":   "\u2699\uFE0F Capa shell - ejecutando comandos...",
    "critic": "\U0001F527 El critic esta corrigiendo el plan...",
}


def tg_action():
    """Burbuja nativa de 'escribiendo...' (dura ~5s; se refresca en hilo aparte)."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{CFG['telegram_token']}/sendChatAction",
            json={"chat_id": CFG["chat_id"], "action": "typing"},
            timeout=8,
        )
    except Exception:
        pass


def tg_stage_send(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{CFG['telegram_token']}/sendMessage",
            json={"chat_id": CFG["chat_id"], "text": text},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("result", {}).get("message_id")
    except Exception as e:
        log.warning("tg_stage_send: %s", str(e)[:120])
    return None


def tg_stage_edit(mid, text):
    if not mid:
        return False
    for attempt in (1, 2, 3):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{CFG['telegram_token']}/editMessageText",
                json={"chat_id": CFG["chat_id"], "message_id": mid,
                      "text": text[:4000]},
                timeout=10,
            )
            if r.status_code == 200 or "message is not modified" in r.text:
                return True
        except Exception as e:
            log.warning("tg_stage_edit intento %d: %s", attempt, str(e)[:120])
        time.sleep(2 * attempt)
    return False


def start_typing(stop_event):
    def _loop():
        while not stop_event.wait(4.5):
            tg_action()
    threading.Thread(target=_loop, daemon=True).start()


# --- Feedback equivalente para la consola (ASCII puro, sin depender de TG) ---
CLI_STAGE = {
    "think":  "  . pensando...",
    "search": "  . buscando en la web...",
    "exec":   "  . ejecutando comandos...",
    "critic": "  . corrigiendo plan...",
}


def cli_progress(name):
    msg = CLI_STAGE.get(name)
    if msg:
        print(msg, flush=True)


def finish_status(mid, reply, alts=""):
    """Convierte el placeholder de estado en la respuesta final.
    Si no se puede editar (red/mensaje viejo), cae a tg_send normal."""
    full = f"{reply}\n\n{alts}" if alts else reply
    if mid and len(full) <= 4000 and tg_stage_edit(mid, full):
        _flush_outbox()
        return
    tg_send(reply)
    if alts:
        time.sleep(1)
        tg_send(alts)


def _flush_outbox():
    """Entrega mensajes que quedaron encolados por fallos de red previos."""
    global store_global
    if not store_global:
        return
    pend = store_global.get("outbox", [])
    if not pend:
        return
    entregados = 0
    for msg in pend[:]:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{CFG['telegram_token']}/sendMessage",
                json={"chat_id": CFG["chat_id"], "text": "[pendiente] " + msg[:3900]},
                timeout=15,
            )
            if r.status_code == 200:
                pend.remove(msg)
                entregados += 1
        except Exception:
            break   # red cayo de nuevo: sigo encolando
    store_global.set("outbox", pend)
    if entregados:
        log.info("outbox: %d mensajes pendientes entregados", entregados)


def notify(text):
    print(text)
    tg_send(text)


# ==============================================================================
# === 7. CLIENTE LLM (OPENROUTER / GEMINI) ====================================


def call_openrouter(prompt, system_instruction):
    """Cualquier API compatible OpenAI (OpenRouter por defecto). 'base_url' en
    config.json permite usar Groq, Ollama local, vLLM u otro proveedor sin tocar codigo.
    El router 'openrouter/free' rota modelos gratuitos; si alguno falla o devuelve
    vacio, se reintenta con un free fijo (solo cuando el proveedor es OpenRouter)."""
    base = str(CFG.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
    models = [CFG["model"]]
    if "openrouter.ai" in base:
        models.append("nvidia/nemotron-3.5-lightning:free")
    for model in models:
        try:
            url = f"{base}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/soyjutex/MicroBot",
                "X-Title": "MicroBot",
            }
            if CFG.get("api_key"):
                headers["Authorization"] = f"Bearer {CFG['api_key']}"
            data = {
                "model": model,
                "max_tokens": 3000,   # modelos con reasoning queman tokens antes del contenido
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
            }
            res = requests.post(url, headers=headers, json=data, timeout=120).json()
            if "choices" not in res:
                raise RuntimeError(f"OpenRouter: {json.dumps(res.get('error', res))[:200]}")
            msg = res["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            if not content:
                # Algunos modelos free dejan el JSON dentro del campo reasoning
                m = re.search(r"\{.*\}", msg.get("reasoning") or "", re.DOTALL)
                if m:
                    return m.group(0)
                raise RuntimeError("OpenRouter: respuesta sin contenido util")
            return content
        except Exception:
            if model == CFG["model"]:
                continue   # proximo intento con el fallback
            raise


def call_gemini(prompt, system_instruction):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{CFG['model']}:generateContent?key={CFG['api_key']}")
    data = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
    }
    res = requests.post(url, headers={"Content-Type": "application/json"}, json=data, timeout=60).json()
    return res["candidates"][0]["content"]["parts"][0]["text"]


def call_llm(prompt, system_instruction):
    if CFG.get("provider", "openrouter") == "gemini":
        return call_gemini(prompt, system_instruction)
    return call_openrouter(prompt, system_instruction)
# ==============================================================================

def check_budget(store, kind="call"):
    """True si hay presupuesto disponible para 'call' o 'auto'."""
    usage = store.get("usage", {})
    today = datetime.date.today().isoformat()
    if usage.get("date") != today:
        usage = {"date": today, "calls": 0, "auto_cycles": 0}
        store.set("usage", usage)
        store.set("circuit_open", False)
        store.set("backoff_until", 0)
    if kind == "call":
        return usage["calls"] < CFG["max_calls_per_day"]
    if kind == "auto":
        return usage["auto_cycles"] < CFG["max_auto_cycles_per_day"]
    return True


def inc_usage(store, kind="call"):
    usage = store.get("usage", {})
    if kind == "call":
        usage["calls"] += 1
    else:
        usage["auto_cycles"] += 1
    store.set("usage", usage)
    warn70 = int(CFG["max_calls_per_day"] * 0.7)
    warn90 = int(CFG["max_calls_per_day"] * 0.9)
    if usage["calls"] in (warn70, warn90):
        tg_send(f"[PRESUPUESTO] {usage['calls']}/{CFG['max_calls_per_day']} llamadas LLM hoy")


def record_error(store, ctx, err):
    store.add_error(ctx, err)
    log.error("error registrado ctx=%s err=%s", ctx, str(err)[:120])
    rate = store.error_rate_last_hour()
    n_errors = len(store.recent_errors(100))
    if (n_errors >= CFG["min_errors_for_breaker"]
            and rate >= CFG["error_threshold"]
            and not store.get("circuit_open")):
        store.set("circuit_open", True)
        store.set("backoff_until", time.time() + CFG["backoff_base_sec"])
        tg_send(f"[BREAKER] Errores autonomos >={int(CFG['error_threshold']*100)}% en 1h. "
                f"Pausa {CFG['backoff_base_sec']//60}min.")


def circuit_open(store):
    return bool(store.get("circuit_open")) and time.time() < store.get("backoff_until", 0)


def build_system_prompt(user_input, store, system_extra=""):
    """Construye la instruccion de sistema completa con todo el contexto del bot.
    La memoria se inyecta por RELEVANCIA (FTS5): solo 3-5 hechos relacionados con
    el mensaje, nunca todo el historial (zero-token bloat)."""
    host, os_name, cpu_model = host_identity()
    hw = f"CPU {cpu_model}" if cpu_model else "hardware generico"
    mem = store.relevant_facts(user_input, 5)
    mem_json = json.dumps(mem, ensure_ascii=False)[:700]
    context = (
        f"HARDWARE REAL: {hw}. Stats ahora: {get_sys_stats()['str']}. "
        f"NUNCA propongas tareas pesadas si hay pocos recursos. "
        f"MEMORIA RELEVANTE (facts filtrados por similitud al mensaje): {mem_json}. "
        f"HISTORIAL RECIENTE: {json.dumps(store.recent_history(5), ensure_ascii=False)}. "
        f"ERRORES RECIENTES: {json.dumps(store.recent_errors(5), ensure_ascii=False)}. "
        f"SCRATCHPAD: {json.dumps(store.recent_scratch(8), ensure_ascii=False)}"
    )
    max_alt = CFG["max_alternatives"]
    return (
        f"Eres MicroBot, admin L4 autonomo de la maquina '{host}' ({os_name}), ciclo cerrado "
        f"PENSAR-ACTUAR-OBSERVAR-APRENDER. Corres con los permisos del servicio en una maquina "
        f"dedicada exclusivamente a ti, "
        f"pero mantenes la lista BLOCKED de comandos destructivos por seguridad propia. {context}. "
        f"MULTI-RESPUESTA: ademas del campo reply (respuesta principal clara y directa), genera hasta {max_alt} "
        f"alternativas utiles en 'alternatives': pueden ser otra forma de resolverlo, una sugerencia extra "
        f"de mantenimiento, o un dato relacionado valioso. Si no aportan valor real, dejalo vacio []. "
        f"MISION_PROTOCOL: 1.ANALIZA 2.EJECUTA 3.OBSERVA 4.CRITICA 5.APRENDE. "
        f"status=SUCCESS cuando la tarea quedo resuelta; FAILED si es imposible; CONTINUE si falta iterar. "
        f"Para charla simple responde directo con status SUCCESS y sin plan (ahorra llamadas). "
        f"Si el mensaje es una PREGUNTA sobre conocimiento o el pasado, NO ejecutes comandos: "
        f"respondé desde MEMORIA RELEVANTE con status SUCCESS. "
        f"Responde SIEMPRE JSON exacto: {{"
        f"\"thought\": \"razonamiento conciso de maximo 2 lineas\", "
        f"\"plan\": [{{\"cmd\": \"bash\", \"expect\": \"esperado\"}}], "
        f"\"search\": \"consulta web opcional SOLO si necesitas datos de internet actuales\", "
        f"\"reply\": \"respuesta principal breve\", "
        f"\"alternatives\": [\"variante opcional\", \"otra opcion extra\"], "
        f"\"new_fact\": \"dato permanente opcional\", "
        f"\"new_skill\": {{\"name\": \"snake_case\", \"code\": \"python con def run(arg='')\", \"desc\": \"...\"}}, "
        f"\"status\": \"CONTINUE|SUCCESS|FAILED\", "
        f"\"patch\": \"codigo completo de ti mismo solo si te piden mejorarte\"}}. "
        f"Para crear habilidades usa new_skill (NO archivos sueltos). Skills: {store.skill_names()}. "
        f"{system_extra}"
    )


def ask_llm(user_input, store, system_extra=""):
    """Consulta al LLM devolviendo texto crudo (JSON esperado)."""
    if not check_budget(store, "call"):
        return json.dumps({"reply": "Limite diario del LLM alcanzado.", "plan": [], "alternatives": []})
    inc_usage(store, "call")
    try:
        return call_llm(user_input, build_system_prompt(user_input, store, system_extra))
    except Exception as e:
        return json.dumps({"reply": f"Error API: {e}", "plan": [], "alternatives": []})


def parse_json_loose(raw):
    """Extrae el primer objeto JSON valido de una respuesta arbitraria del LLM."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


MAX_SEARCH_CHARS = 600   # coto duro anti-explosion de tokens
MAX_RESULTS = 3


def web_search(query):
    """Busqueda web quirurgica via DuckDuckGo Lite (HTML minimo, sin API key).
    Devuelve maximo 3 resultados y 600 caracteres en total: titulo + snippet corto."""
    try:
        r = requests.post("https://lite.duckduckgo.com/lite/", data={"q": query[:200]},
                          headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
                          timeout=15)
        links = re.findall(r'<a[^>]+href="(http[^"]+)"[^>]*>(.*?)</a>', r.text)
        snips = [re.sub(r"<[^>]+>", "", s).strip()
                 for s in re.findall(r'class=["\']result-snippet["\'][^>]*>(.*?)</td>',
                                     r.text, re.DOTALL)]
        out, total = [], 0
        si = 0
        for url, raw_title in links:
            title = re.sub(r"<[^>]+>", "", raw_title).strip()
            if not title or "duckduckgo" in url:
                continue
            snippet = ""
            if si < len(snips):
                snippet = snips[si]
                si += 1
            piece = f"- {title}: {snippet} [{url}]"
            if len(piece) > MAX_SEARCH_CHARS - total:
                break
            out.append(piece)
            total += len(piece)
            if len(out) >= MAX_RESULTS:
                break
        return "\n".join(out) if out else "(sin resultados utiles)"
    except Exception as e:
        return f"[busqueda fallo: {e}]"


def critic_loop(store, task, results):
    """Segunda pasada: analiza resultados, aprende hechos y puede proponer skills."""
    if not check_budget(store, "call"):
        return ""
    inc_usage(store, "call")
    prompt = (f"TAREA: {task}\nRESULTADOS: {json.dumps(results[-3:], ensure_ascii=False)[:2500]}\n"
              f"Analiza: objetivo cumplido? que fallo? que hecho guardar? vale una skill nueva? "
              f"JSON: {{\"fix_fact\":\"\",\"new_skill\":{{\"name\":\"\",\"code\":\"\",\"desc\":\"\"}},\"reply\":\"breve\"}}")
    try:
        txt = call_llm(prompt, "Eres el critic. Solo JSON.")
        c = parse_json_loose(txt) or {}
        fact = (c.get("fix_fact") or "").strip()
        if fact and fact.lower() not in ("", "vacio", "none", "null"):
            store.add_fact(fact)
        sk = c.get("new_skill")
        if isinstance(sk, dict) and sk.get("name") and sk.get("code"):
            install_skill(store, sk["name"], sk["code"], sk.get("desc", ""))
        return c.get("reply", "")
    except Exception:
        return ""


# ==============================================================================
# === 8. SKILLS (python reutilizable validado) ================================
# ==============================================================================

def validate_code(code):
    """Valida sintaxis y tamano razonable antes de aceptar codigo generado."""
    if not code or not code.strip():
        return False, "codigo vacio"
    if len(code) > 120000:
        return False, "demasiado grande"
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"syntax error: {e}"
    return True, "ok"


def test_skill(code, test_input=""):
    """Corre la skill en namespace aislado; acepta run(arg) o test(arg)."""
    import io, contextlib
    try:
        ns = {}
        exec(compile(code, "skill", "exec"), ns, ns)
        fn = ns.get("test") or ns.get("run")
        if not fn:
            return False, "sin test() ni run()"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                r = fn(test_input)
            except TypeError:
                r = fn()
        printed = buf.getvalue().strip()
        if r is not None:
            return True, str(r)
        if printed:
            return True, printed
        return True, "(ejecutado sin salida)"
    except Exception as e:
        return False, str(e)


def install_skill(store, name, code, desc=""):
    ok, msg = validate_code(code)
    if not ok:
        return f"[SKILL RECHAZADA] {name}: {msg}"
    store.save_skill(name, code, desc)
    ok, tout = test_skill(code)
    return f"[SKILL GUARDADA] {name} (test: {'OK' if ok else 'FALLO'}: {tout[:100]})"


def run_skill(store, name, arg=""):
    sk = store.get_skill(name)
    if not sk:
        return f"[SKILL NO EXISTE] {name}"
    ok, out = test_skill(sk["code"], arg)
    return f"[SKILL {name}] {out}" if ok else f"[SKILL ERROR] {name}: {out}"


# ==============================================================================
# === 9. GESTION DE TURNOS (CON MULTI-RESPUESTA) ==============================
# ==============================================================================

def extract_actions(data, store, out_list):
    """Procesa acciones secundarias de la respuesta del LLM: facts, skills."""
    fact = (data.get("new_fact") or "").strip()
    if fact and fact.lower() not in ("", "vacio", "none", "null"):
        store.add_fact(fact)
        out_list.append(f"[memoria] {fact}")
    sk = data.get("new_skill")
    if isinstance(sk, dict) and sk.get("name") and sk.get("code"):
        out_list.append(install_skill(store, sk["name"], sk["code"], sk.get("desc", "")))


def format_alternatives(alternatives):
    """Formatea las respuestas alternativas para entrega separada por Telegram."""
    alts = [a.strip() for a in alternatives if isinstance(a, str) and a.strip()]
    if not alts:
        return ""
    lines = ["🤖 *Variantes:*"]
    for i, alt in enumerate(alts, 1):
        lines.append(f"{i}. {alt}")
    return "\n".join(lines)


def handle_turn(user_input, store, progress=None):
    """
    Procesa un turno completo de conversacion.
    Devuelve (respuesta_principal, alternativas_formateadas).
    progress(nombre_etapa) opcional: avisa en que capa del pipeline va.
    """
    if progress:
        progress("think")
    raw = ask_llm(user_input, store)
    data = parse_json_loose(raw) or {"plan": [], "reply": "", "alternatives": []}
    if not data.get("reply") and not data.get("plan"):
        # respuesta vacia/ilegible del modelo: un unico reintento
        if progress:
            progress("think")
        raw2 = ask_llm(
            user_input, store,
            "(tu respuesta anterior llego vacia o ilegible; "
            "repeti SOLO el JSON)")
        data2 = parse_json_loose(raw2)
        if data2:
            data = data2
    if not data.get("reply") and not data.get("plan"):
        record_error(store, "handle_turn",
                     "respuesta LLM vacia o ilegible incluso tras reintento "
                     "(router free saturado o red intermitente)")

    # Herramienta de busqueda web: si el modelo la pide, se ejecuta UNA vez,
    # se inyectan los resultados recortados y se hace una sola pasada final.
    if isinstance(data.get("search"), str) and data["search"].strip():
        if progress:
            progress("search")
        results = web_search(data["search"].strip())
        if progress:
            progress("think")
        raw2 = ask_llm(
            user_input, store,
            f"RESULTADOS DE BUSQUEDA WEB para '{data['search'][:80]}' (recortados, "
            f"verifica vigencia antes de afirmar):\n{results}\n"
            "Con esto respondé el JSON final. NO vuelvas a pedir search.")
        data2 = parse_json_loose(raw2)
        if data2:
            data = data2

    out = []
    extract_actions(data, store, out)

    status = (data.get("status") or "CONTINUE").upper()
    reply = (data.get("reply") or "").strip()
    alternatives = format_alternatives(data.get("alternatives", []))

    if status == "SUCCESS" and not data.get("plan"):
        # Charla simple: solo respuesta (1 llamada, barato)
        if reply:
            out.insert(0, reply)
    elif status == "FAILED":
        out.insert(0, "❌ TAREA FALLO")
    else:
        plan = data.get("plan", [])
        if plan:
            if progress:
                progress("exec")
            results, ok = exec_plan(plan, store)
            for r in results:
                failed = ("BLOQUEADO" in r["out"] or "TIMEOUT" in r["out"])
                em = "❌" if failed else "⚙️"
                out.append(f"{em} {r['cmd']}\n{r['out']}")
            if not ok:
                if progress:
                    progress("critic")
                c = critic_loop(store, user_input, [r["out"] for r in results])
                if c:
                    out.append(f"[critic] {c[:400]}")
        if reply:
            out.insert(0, reply)

    store.add_history(user_input, reply or "(ejecuto plan)")
    main_response = "\n".join(out) if out else "(sin respuesta)"
    return main_response, alternatives


def exec_plan(plan, store):
    """Ejecuta pasos secuenciales; corta ante bloqueo o timeout. Devuelve (resultados, ok)."""
    results = []
    for i, step in enumerate(plan):
        cmd = step.get("cmd", "") if isinstance(step, dict) else str(step)
        expect = step.get("expect", "") if isinstance(step, dict) else ""
        out = run_cmd(cmd)
        store.add_scratch(f"turno paso {i+1}", cmd, out)
        results.append({"cmd": cmd, "out": out})
        if "BLOQUEADO" in out or "TIMEOUT" in out or "Error API" in out:
            return results, False
    return results, True


# ==============================================================================
# === 10. MISIONES (BUCLE AGENTE MULTI-PASO) ==================================
# ==============================================================================

def run_mission(store, goal):
    """Bucle agente de max N pasos con corte anti-bucle y pausas inteligentes."""
    max_steps = CFG["mission_max_steps"]
    log_steps = []
    notify(f"[MISION] {goal}\nMax {max_steps} pasos (anti-bucle). Recursos: {get_sys_stats()['str']}")

    for step in range(max_steps):
        if not check_budget(store, "call"):
            store.add_mission(goal, len(log_steps), "sin_presupuesto")
            notify("[MISION PAUSADA] presupuesto diario agotado.")
            return
        if not resources_ok():
            store.add_mission(goal, len(log_steps), "recursos_bajos")
            notify(f"[MISION PAUSA RECURSOS] {get_sys_stats()['str']} - reintentá mas tarde.")
            return

        prompt = (f"MISION: {goal}\nPASOS YA HECHOS: {json.dumps(log_steps[-5:], ensure_ascii=False)}\n"
                  f"Si la mision YA esta completa responde {{\"mission_complete\": true, \"reply\": \"...\", "
                  f"\"alternatives\": [...]}}. "
                  f"Si necesitas info del usuario responde {{\"needs_help\": true, \"help_question\": \"...\"}}. "
                  f"Si falta trabajo da UN solo comando en plan.")
        raw = ask_llm(prompt, store, f"Modo mision: paso {step+1} de {max_steps}. Eficiente con recursos.")
        data = parse_json_loose(raw) or {}

        extra = []
        extract_actions(data, store, extra)
        if extra:
            notify("\n".join(extra))

        plan = data.get("plan", [])
        if plan:
            cmd = plan[0].get("cmd", "") if isinstance(plan[0], dict) else str(plan[0])
            out = run_cmd(cmd)
            log_steps.append({"paso": step + 1, "cmd": cmd, "out": out[:500]})
            store.add_scratch(f"mision '{goal[:60]}' paso {step+1}", cmd, out)
            notify(f"Paso {step+1}/{max_steps}\ncmd: {cmd}\nout: {out[:800]}")

            if ("Permiso denegado" in out or "Permission denied" in out) and not cmd.strip().startswith("sudo"):
                store.add_mission(goal, len(log_steps), "falta_permiso_root")
                notify("[MISION PAUSADA] Falta root efectivo. Revisá permisos del servicio.")
                return
            c = critic_loop(store, f"mision '{goal[:80]}' paso {step+1}", [out])
            if c:
                notify(f"[critic] {c[:600]}")

        if data.get("mission_complete"):
            store.add_mission(goal, len(log_steps), "completada")
            final_reply = "[MISION COMPLETADA]\n" + (data.get("reply") or "")
            alts = format_alternatives(data.get("alternatives", []))
            if alts:
                final_reply += "\n\n" + alts
            notify(final_reply)
            return
        if data.get("needs_help"):
            store.add_mission(goal, len(log_steps), "necesita_ayuda")
            notify(f"[MISION NECESITA AYUDA] {data.get('help_question') or 'faltan datos'}\n"
                   f"Respondé este mensaje con la info y lanzala de nuevo.")
            return
        time.sleep(2)

    store.add_mission(goal, max_steps, "cortada_por_limite")
    notify("[MISION CORTADA] limite de pasos alcanzado sin completar (proteccion anti-bucle).")


# ==============================================================================
# === 11. COMANDOS LOCALES (SLASH-COMMANDS, NO GASTAN API) ====================
# ==============================================================================

RESTART_SENTINEL = "__RESTART__"


def dispatch(text, store):
    """Comandos locales. Devuelve (True, salida) | ('mision', goal) | (False, None)."""
    if text == "/help":
        return True, ("/help /status /recursos /memoria /errors /skills /skill save|test|run|del <nombre> "
                      "/nota <texto> /notas /idea <texto> /ideas "
                      "/mision <objetivo> /misiones /auto on|off /stopauto /resetauto /restart\n"
                      f"Misiones: max {CFG['mission_max_steps']} pasos. "
                      f"Limites: {CFG['max_calls_per_day']} calls/dia, {CFG['max_auto_cycles_per_day']} auto/dia.")

    if text == "/status":
        u = store.get("usage", {})
        return True, (f"calls {u.get('calls', 0)}/{CFG['max_calls_per_day']} "
                      f"auto {u.get('auto_cycles', 0)}/{CFG['max_auto_cycles_per_day']} "
                      f"auto={'on' if store.get('auto') else 'off'} "
                      f"breaker={'OPEN' if circuit_open(store) else 'closed'} "
                      f"hechos {store.count_facts()} errors {len(store.recent_errors(100))} "
                      f"skills {len(store.skill_names())}")

    if text == "/recursos":
        s = get_sys_stats()
        return True, f"load={s['load1']} ram={s['ram_free']}MB/{s['ram_total']}MB temp={s['temp']} recursos_ok={resources_ok()}"

    if text == "/memoria":
        facts = store.facts(20)
        return True, "\n".join(facts) or "(vacia)"

    if text.startswith("/nota ") or text.startswith("/idea "):
        kind = "notas" if text.startswith("/nota ") else "ideas"
        entry = {"ts": now_iso(), "text": text.split(" ", 1)[1].strip()[:300]}
        if not entry["text"]:
            return True, f"uso: /{kind[:-1]} <texto>"
        lst = store.get(kind, [])
        lst.append(entry)
        lst = lst[-50:]
        store.set(kind, lst)
        return True, f"{kind[:-1]} guardada (total {len(lst)})"

    if text in ("/notas", "/ideas"):
        kind = "notas" if text == "/notas" else "ideas"
        lst = store.get(kind, [])[-10:]
        return True, ("\n".join(f"{e['ts'][:16]} {e['text']}" for e in reversed(lst))
                      or "(vacio)")

    if text == "/errors":
        errs = [f"{e[0][:19]} {e[1]}: {e[2][:80]}" for e in store.recent_errors(10)]
        return True, "\n".join(errs) or "(sin errores)"

    if text == "/skills":
        names = []
        for n in store.skill_names():
            sk = store.get_skill(n)
            names.append(f"{n}: {sk['desc'][:60]}")
        return True, "\n".join(names) or "(sin skills)"

    if text == "/misiones":
        ms = [f"{m[0][:16]} [{m[3]}] {m[1][:60]} ({m[2]} pasos)" for m in store.recent_missions(10)]
        return True, "\n".join(ms) or "(sin misiones)"

    if text.startswith("/mision "):
        goal = text[len("/mision "):].strip()
        if not goal:
            return True, "uso: /mision <objetivo concreto>"
        return "mision", goal

    if text.startswith("/skill "):
        parts = text.split(maxsplit=3)
        if len(parts) < 3:
            return True, "uso: /skill save|test|del|run <nombre> [codigo|arg]"
        act, name = parts[1], parts[2]
        if act == "save" and len(parts) == 4:
            return True, install_skill(store, name, parts[3])
        if act == "test":
            return True, run_skill(store, name)
        if act == "run":
            return True, run_skill(store, name, parts[3] if len(parts) == 4 else "")
        if act == "del":
            store.del_skill(name)
            return True, f"skill {name} borrada"
        return True, "acciones: save|test|del|run"

    if text.startswith("/auto"):
        arg = text.split()[-1] if len(text.split()) > 1 else ""
        if arg == "on":
            store.set("auto", True)
            return True, "auto ON"
        if arg == "off":
            store.set("auto", False)
            return True, "auto OFF"
        return True, f"auto={'on' if store.get('auto') else 'off'}"

    if text == "/stopauto":
        store.set("auto", False)
        return True, "auto detenido"

    if text == "/resetauto":
        store.set("circuit_open", False)
        store.set("backoff_until", 0)
        return True, "breaker reseteado"

    if text == "/restart":
        return True, RESTART_SENTINEL

    return False, None


# ==============================================================================
# === 12. DAEMONS (TELEGRAM + AUTO-CICLOS) ====================================
# ==============================================================================

def compress_memory(store):
    """Compresion nocturna de memoria: UNA llamada LLM para consolidar hechos
    duplicados/obsoletos. Guarda backup previo en kv y no aplica nada si la
    respuesta no parsea bien."""
    rows = store.all_facts(120)
    if len(rows) < 10:
        return "pocas facts, nada que consolidar"
    old_texts = [r[2] for r in rows]
    facts_text = "\n".join(f"- {t}" for t in old_texts)
    prompt = (
        "[COMPRESION DE MEMORIA] Hechos acumulados:\n"
        f"{facts_text}\n\n"
        "Devolveme SOLO un array JSON consolidando estos hechos EXISTENTES: fusiona duplicados "
        "textualmente, elimina solo lo obsoleto o trivial, maximo 40 items, cada uno breve. "
        "PROHIBIDO inventar, agregar o reformular datos que no esten en la lista de arriba. "
        'Formato exacto: ["hecho 1", "hecho 2", ...]'
    )
    raw = ask_llm(prompt, store, "Modo mantenimiento nocturno: responde SOLO el array JSON.")
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return "respuesta no parseable: no cambio nada"
    try:
        new_facts = json.loads(m.group(0))
        if not isinstance(new_facts, list) or not new_facts or len(new_facts) > 60:
            return "lista invalida: no cambio nada"
        clean = [str(x).strip()[:500] for x in new_facts if str(x).strip()]
        store.set("facts_backup_" + datetime.date.today().isoformat(),
                  {"ids": [r[0] for r in rows], "ts": [r[1] for r in rows], "texts": old_texts})
        store.replace_facts(clean)
        return f"memoria consolidada: {len(rows)} -> {len(clean)} facts (backup en kv)"
    except Exception as e:
        return f"error en consolidacion: {e} (no cambio nada)"


def auto_worker(store):
    """Hilo de fondo: rutina nocturna 04:00 (compresion de memoria) y
    auto-mejora cada N segundos si hay presupuesto y recursos."""
    while True:
        time.sleep(CFG["auto_interval_sec"])
        try:
            # --- rutina nocturna (una vez por dia, a las 04:00) ---
            now = datetime.datetime.now()
            today = now.date().isoformat()
            if now.hour == 4 and store.get("last_compress") != today:
                store.set("last_compress", today)
                if not circuit_open(store) and resources_ok() and check_budget(store, "call"):
                    r = compress_memory(store)
                    log.info("compresion nocturna: %s", r)
                    tg_send(f"[MANTENIMIENTO] {r}")

            if not store.get("auto"):
                continue
            if circuit_open(store):
                continue
            if not (check_budget(store, "auto") and check_budget(store, "call")):
                continue
            if not resources_ok():
                tg_send(f"[AUTO pausado] recursos bajos: {get_sys_stats()['str']}")
                continue
            inc_usage(store, "auto")
            state = run_cmd("uptime; df -h / | tail -2; free -h | head -2; journalctl -n 10 --no-pager 2>&1 | tail -8")
            prompt = (f"[AUTO-CICLO] Estado:\n{state}\n"
                      "Elegi UNA accion concreta y util: fix, limpieza segura, guardar hecho, "
                      "crear/testear skill. Nada pesado.")
            reply, alts = handle_turn(prompt, store)
            msg = reply[:3800]
            if alts:
                msg += "\n\n" + alts[:1500]
            tg_send(msg)
        except Exception as e:
            record_error(store, "auto_worker", e)


_LOCK_FD = None


class InstanceLock:
    """Lock de instancia unica: flock en Unix, msvcrt.locking en Windows."""

    def __init__(self):
        self._fh = None

    def acquire(self):
        self._fh = open(PID_FILE, "w")
        try:
            if IS_WINDOWS:
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("MicroBot ya corriendo (lock activo).", file=sys.stderr)
            sys.exit(1)
        self._fh.write(str(os.getpid()))
        self._fh.flush()

    def release(self):
        try:
            if self._fh:
                self._fh.close()
            os.remove(PID_FILE)
        except OSError:
            pass


_LOCK = InstanceLock()


def acquire_lock():
    """Garantiza instancia unica via lock sobre el PID file (robusto ante PIDs reciclados)."""
    _LOCK.acquire()


def release_lock():
    _LOCK.release()


def telegram_daemon():
    store = Store(DB_FILE)
    acquire_lock()
    threading.Thread(target=auto_worker, args=(store,), daemon=True).start()
    tg_send(f"MicroBot v8.0 online.\n{get_sys_stats()['str']}\nPipeline visible. /help")
    log.info("daemon iniciado (pid %s)", os.getpid())
    last_update = 0
    try:
        while True:
            try:
                r = requests.get(
                    f"https://api.telegram.org/bot{CFG['telegram_token']}/getUpdates",
                    params={"offset": last_update + 1, "timeout": 30}, timeout=35).json()
                for u in r.get("result", []):
                    last_update = u["update_id"]
                    msg = u.get("message", {})
                    if str(msg.get("chat", {}).get("id")) != str(CFG["chat_id"]):
                        continue
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    log.info("mensaje recibido: %s", text[:80])
                    stop_typing = threading.Event()
                    start_typing(stop_typing)
                    status_id = tg_stage_send(STAGE_MSG["recv"])

                    def stage(name, sid=status_id):
                        if sid:
                            tg_stage_edit(sid, STAGE_MSG[name])

                    try:
                        kind, out = dispatch(text, store)
                        if kind is True:
                            if out == RESTART_SENTINEL:
                                do_restart()
                            else:
                                finish_status(status_id, out)
                            continue
                        if kind == "mision":
                            executor.submit(run_mission, store, out)
                            finish_status(status_id, f"🎯 Misión iniciada:\n{out}")
                            continue
                        reply, alts = handle_turn(text, store, progress=stage)
                        finish_status(status_id, reply, alts)
                    finally:
                        stop_typing.set()
            except Exception as e:
                record_error(store, "telegram_loop", e)
                time.sleep(3)
    finally:
        release_lock()


def do_restart():
    tg_send("Reiniciando (systemd me revivira en segundos)...")
    release_lock()
    time.sleep(1)
    sys.exit(0)


# ==============================================================================
# === 13. CLI Y PUNTO DE ENTRADA ==============================================
# ==============================================================================

def cli():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    store = Store(DB_FILE)
    if len(sys.argv) == 1:
        print(f"MicroBot v8 universal - misiones + planes + skills + critic. "
              f"Limites: {CFG['max_calls_per_day']}/dia. /help")
        while True:
            try:
                text = input("\n[tu] > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text.lower() in ("salir", "exit", "quit"):
                break
            print(". mensaje recibido", flush=True)
            kind, out = dispatch(text, store)
            if kind is True:
                print(out)
                continue
            if kind == "mision":
                run_mission(store, out)
                continue
            reply, alts = handle_turn(text, store, progress=cli_progress)
            print(reply)
            if alts:
                print("\n" + alts)
        return

    arg = " ".join(sys.argv[1:])
    if arg in ("--daemon", "-d"):
        telegram_daemon()
    elif arg == "--compactar":
        print(compress_memory(store))
    elif arg in ("--help", "-h"):
        print("microbot [msg] | --daemon | --status | --help")
    elif arg == "--status":
        _, out = dispatch("/status", store)
        print(out)
    elif arg.startswith("/"):
        kind, out = dispatch(arg, store)
        if kind is True:
            if out == RESTART_SENTINEL:
                do_restart()
            else:
                print(out)
        elif kind == "mision":
            run_mission(store, out)
        else:
            print(f"comando desconocido: {arg}")
    else:
        print(". mensaje recibido", flush=True)
        reply, alts = handle_turn(arg, store, progress=cli_progress)
        print(reply)
        if alts:
            print("\n" + alts)


if __name__ == "__main__":
    cli()
