#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MicroBot v8.0 Universal - Autonomous Edge AI Agent & SysAdmin
Single-file, multiplatform (Linux/macOS/Windows/Termux).
RAM ~35MB | Deps: Python 3.10+ + requests.
"""

import os, sys, json, time, datetime, threading, subprocess, re, ast, platform, sqlite3, html, tempfile
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor
import requests

# =====================================================================
# 1. PLATFORM ABSTRACTION LAYER (PAL)
# =====================================================================
OS_NAME = platform.system()
IS_WINDOWS = OS_NAME == "Windows"
IS_MACOS = OS_NAME == "Darwin"
IS_LINUX = OS_NAME == "Linux"

# Datos y config viven junto al script: una carpeta = instalacion completa.
# Override opcional con MICROBOT_DATA_DIR (p.ej. systemd con sandbox).
BASE_DIR = os.getenv("MICROBOT_DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(BASE_DIR, exist_ok=True)
DB_FILE = os.path.join(BASE_DIR, "microbot.db")
PID_FILE = os.path.join(tempfile.gettempdir(), "microbot.pid")
SELF_FILE = os.path.abspath(__file__)

# ---- TELEMETRÍA ----
def _telemetry():
    out = {"ram_free_mb": 0, "ram_total_mb": 0, "cpu_pct": None, "temp_c": None, "disk_pct": None, "load1": None}
    if IS_WINDOWS:
        try:
            import ctypes
            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                            ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                            ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                            ("ullAvailExtendedVirtual", ctypes.c_uint64)]
            st = MemStatus(); st.dwLength = ctypes.sizeof(MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                out["ram_total_mb"] = st.ullTotalPhys // 1048576
                out["ram_free_mb"] = st.ullAvailPhys // 1048576
        except Exception: pass
        try:
            import ctypes
            class FileTime(ctypes.Structure):
                _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]
            def ft(ft): return (ft.hi << 32) + ft.lo
            k32 = ctypes.windll.kernel32
            i1,k1,u1 = FileTime(),FileTime(),FileTime()
            k32.GetSystemTimes(ctypes.byref(i1),ctypes.byref(k1),ctypes.byref(u1))
            time.sleep(0.25)
            i2,k2,u2 = FileTime(),FileTime(),FileTime()
            k32.GetSystemTimes(ctypes.byref(i2),ctypes.byref(k2),ctypes.byref(u2))
            tot = (ft(k2)-ft(k1)) + (ft(u2)-ft(u1))
            busy = tot - (ft(i2)-ft(i1))
            out["cpu_pct"] = round(busy*100/tot, 1) if tot else None
        except Exception: pass
    else:
        try:
            with open("/proc/meminfo") as f:
                mi = {l.split(":")[0].strip(): int(l.split(":")[1].split()[0]) for l in f.readlines()[:10]}
            out["ram_total_mb"] = mi.get("MemTotal",0)//1024
            out["ram_free_mb"] = mi.get("MemAvailable", mi.get("MemFree",0))//1024
        except Exception: pass
        try:
            out["load1"] = float(open("/proc/loadavg").read().split()[0])
            ncpu = os.cpu_count() or 1
            out["cpu_pct"] = min(round(out["load1"]*100/ncpu,1), 100)
        except Exception: pass
        if not IS_MACOS:
            try:
                out["temp_c"] = int(open("/sys/class/thermal/thermal_zone0/temp").read())//1000
            except Exception: pass
    try:
        st = os.statvfs(BASE_DIR if not IS_WINDOWS else os.getenv("SystemDrive","C:")+"\\")
        out["disk_pct"] = round((st.f_blocks-st.f_bfree)*100/st.f_blocks,1)
    except Exception: pass
    return out

def get_stats():
    t = _telemetry()
    parts = []
    if t["cpu_pct"] is not None: parts.append(f"CPU={t['cpu_pct']}%")
    parts.append(f"RAM={t['ram_free_mb']}MB libres de {t['ram_total_mb']}MB")
    if t["temp_c"] is not None: parts.append(f"Temp={t['temp_c']}°C")
    if t["load1"] is not None: parts.append(f"Load={t['load1']}")
    if t["disk_pct"] is not None: parts.append(f"Disk={t['disk_pct']}%")
    return {"str": " | ".join(parts) or "stats N/A", **t}

def resources_ok():
    s = get_stats()
    ram_ok = s["ram_free_mb"] >= CFG["ram_min_mb"]
    if s["cpu_pct"] is not None: return ram_ok and s["cpu_pct"] <= CFG["cpu_max_pct"]
    if s["load1"] is not None: return ram_ok and s["load1"] <= CFG["load_max"]
    return ram_ok

# ---- SHELL ----
BLOCKED_UNIX = [r"rm\s+-[rf]{1,2}\s*/(?:\s|$)", r"--no-preserve-root",
                r"mkfs", r"dd\s+if=", r":\(\)\s*\{\s*:\|\:&\s*;\s*\}",
                r"shutdown", r"reboot", r"halt", r">\s*/dev/sd", r"chmod\s+-R\s+777\s+/\b"]
BLOCKED_WIN = [r"Format-Volume", r"Remove-Item\s+-Recurse\s+[A-Za-z]:\\",
               r"rd\s+/s\s+/q\s+[A-Za-z]:\\", r"shutdown", r"bcdedit", r"reg\s+delete\s+HKLM",
               r"format\s+[a-z]:", r"diskpart"]
BLOCKED = BLOCKED_WIN if IS_WINDOWS else BLOCKED_UNIX

def run_cmd(cmd):
    for pat in BLOCKED:
        if re.search(pat, cmd, re.IGNORECASE): return "[BLOQUEADO] Comando peligroso."
    try:
        full = ["powershell","-NoProfile","-NonInteractive","-Command",cmd] if IS_WINDOWS else ["bash","-c",cmd]
        r = subprocess.run(full, capture_output=True, text=True, timeout=CFG["cmd_timeout_sec"],
                           errors="replace", env={**os.environ,"PYTHONIOENCODING":"utf-8"})
        out = (r.stdout or "") + (("\n"+r.stderr) if r.stderr else "")
        return out.strip()[:4000] if out.strip() else "(sin salida)"
    except subprocess.TimeoutExpired: return f"[TIMEOUT {CFG['cmd_timeout_sec']}s]"
    except Exception as e: return f"[ERROR] {e}"

# ---- LOCK ----
if IS_WINDOWS: import msvcrt
else: import fcntl

class InstanceLock:
    def __init__(self):
        self._fh = None
    def acquire(self):
        self._fh = open(PID_FILE, "w")
        try:
            if IS_WINDOWS: msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else: fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("MicroBot ya corriendo.", file=sys.stderr); sys.exit(1)
        self._fh.write(str(os.getpid())); self._fh.flush()
    def release(self):
        try:
            if self._fh: self._fh.close()
            os.remove(PID_FILE)
        except Exception: pass

# =====================================================================
# 2. CONFIG
# =====================================================================
def load_config():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_file = os.getenv("MICROBOT_CONFIG", os.path.join(script_dir, "config.json"))
    # Fallback legacy: ~/.microbot/config.json
    if not os.path.exists(cfg_file):
        alt = os.path.join(os.path.expanduser("~/.microbot"), "config.json")
        if os.path.exists(alt): cfg_file = alt
    file_cfg = {}
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f: file_cfg = json.load(f)
        except Exception: pass
    def env(key, default): return os.getenv(f"MICROBOT_{key.upper()}", default)
    return {
        "api_key":        env("API_KEY", file_cfg.get("api_key", "")),
        "base_url":       env("BASE_URL", file_cfg.get("base_url", "https://openrouter.ai/api/v1")),
        "model":          env("MODEL", file_cfg.get("model", "openrouter/free")),
        "telegram_token": env("TELEGRAM_TOKEN", file_cfg.get("telegram_token", "")),
        "chat_id":        str(env("CHAT_ID", file_cfg.get("chat_id", ""))),
        "max_calls_day":  int(file_cfg.get("max_calls_day", 45)),
        "max_substeps":   int(file_cfg.get("max_substeps", 3)),
        "cmd_timeout_sec": int(file_cfg.get("cmd_timeout_sec", 60)),
        "mission_max_steps": int(file_cfg.get("mission_max_steps", 6)),
        "ram_min_mb":      int(file_cfg.get("ram_min_mb", 120)),
        "cpu_max_pct":     int(file_cfg.get("cpu_max_pct", 85)),
        "load_max":        float(file_cfg.get("load_max", 4.0)),
    }

CFG = load_config()

# =====================================================================
# 3. SQLITE + FTS5 BRAIN
# =====================================================================
def init_db():
    with sqlite3.connect(DB_FILE) as c:
        c.execute("PRAGMA journal_mode=WAL;")   # Write-Ahead Logging: lecturas concurrentes sin esperas
        c.execute("PRAGMA busy_timeout=5000;")  # espera hasta 5s en vez de fallar con 'database is locked'
        c.executescript("""
        CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, fact TEXT UNIQUE, ts TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(fact, content='facts', content_rowid='id');
        CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, user TEXT, bot TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY, task TEXT, done INTEGER DEFAULT 0, ts TEXT);
        CREATE TABLE IF NOT EXISTS notes (key TEXT PRIMARY KEY, value TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS ideas (id INTEGER PRIMARY KEY, idea TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS skills (name TEXT PRIMARY KEY, code TEXT, desc TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS usage (date TEXT PRIMARY KEY, calls INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, text TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS schedules (id INTEGER PRIMARY KEY, schedule_time TEXT, task TEXT, daily INTEGER DEFAULT 0, last_run TEXT);
        """)
        c.commit()

init_db()

def db():
    c = sqlite3.connect(DB_FILE); c.row_factory = sqlite3.Row; return c

STOPWORDS = frozenset("""
de la el los las un una unos unas y o a en que al del lo se su por para con sin sobre
es son esta estan fue ser soy estoy me mi mis tu tus le les hay the and for with this
that what when where how your you are was were have has had not but all can dime decime
hace hacer quiero podes""".split())

def search_facts(query, limit=4):
    kws = [w for w in re.findall(r"[a-z0-9]{4,}", query.lower()) if w not in STOPWORDS][:5]
    if not kws:
        return [r["fact"] for r in db().execute("SELECT fact FROM facts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    try:
        q = " OR ".join(f'"{k.replace(chr(34), chr(34)*2)}"' for k in kws)
        rows = db().execute(f"SELECT fact FROM facts_fts WHERE facts_fts MATCH ? LIMIT ?", (q, limit)).fetchall()
        if rows: return [r["fact"] for r in rows]
    except Exception: pass
    return [r["fact"] for r in db().execute("SELECT fact FROM facts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

def add_fact(text):
    clean = text.strip()
    if not clean or len(clean) < 5: return
    with db() as c:
        cur = c.execute("INSERT OR IGNORE INTO facts (fact, ts) VALUES (?, ?)", (clean[:500], datetime.datetime.now().isoformat()))
        if cur.lastrowid: c.execute("INSERT INTO facts_fts (rowid, fact) VALUES (?, ?)", (cur.lastrowid, clean[:500]))
        c.commit()

def add_history(u, b):
    with db() as c:
        c.execute("INSERT INTO history (user, bot, ts) VALUES (?, ?, ?)", (u[:500], b[:500], datetime.datetime.now().isoformat()))
        c.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 40)")
        c.commit()

# ---- KV / BUDGET / OUTBOX ----
def kv_get(key, default=None):
    r = db().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else default

def kv_set(key, value):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        c.commit()

def budget_ok():
    today = datetime.date.today().isoformat()
    row = db().execute("SELECT calls FROM usage WHERE date=?", (today,)).fetchone()
    return (row[0] if row else 0) < CFG["max_calls_day"]

def inc_budget(err=False):
    today = datetime.date.today().isoformat()
    with db() as c:
        c.execute("""INSERT INTO usage (date, calls) VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET calls = calls + 1""", (today,))
        c.commit()

def outbox_add(text):
    with db() as c:
        c.execute("INSERT INTO outbox (text, ts) VALUES (?, ?)", (text[:4000], datetime.datetime.now().isoformat()))
        c.commit()

def outbox_flush():
    with db() as c:
        rows = c.execute("SELECT id, text FROM outbox ORDER BY id").fetchall()
        for r in rows:
            if tg_send_raw(r["text"]):
                c.execute("DELETE FROM outbox WHERE id=?", (r["id"],))
        c.commit()

# =====================================================================
# 4. TELEGRAM CORE (PIPELINE VISIBLE + OUTBOX)
# =====================================================================
STAGE = {
    "recv": "📨 Mensaje recibido — entrando al pipeline...",
    "think": "🧠 Pensando — consultando al modelo...",
    "search": "🌐 Capa web — buscando en internet...",
    "exec": "⚙️ Capa shell — ejecutando comandos...",
}

def tg_action():
    try: requests.post(f"https://api.telegram.org/bot{CFG['telegram_token']}/sendChatAction",
        json={"chat_id": CFG["chat_id"], "action": "typing"}, timeout=8)
    except Exception: pass

def tg_send_raw(text):
    try:
        r = requests.post(f"https://api.telegram.org/bot{CFG['telegram_token']}/sendMessage",
            json={"chat_id": CFG["chat_id"], "text": text[:4000]}, timeout=15)
        return r.status_code == 200
    except Exception: return False

def tg_stage_send(text):
    try:
        r = requests.post(f"https://api.telegram.org/bot{CFG['telegram_token']}/sendMessage",
            json={"chat_id": CFG["chat_id"], "text": text}, timeout=10)
        if r.status_code == 200: return r.json()["result"]["message_id"]
    except Exception: pass
    return None

def tg_stage_edit(mid, text):
    if not mid: return False
    for _ in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{CFG['telegram_token']}/editMessageText",
                json={"chat_id": CFG["chat_id"], "message_id": mid, "text": text[:4000]}, timeout=10)
            if r.status_code == 200 or "message is not modified" in r.text: return True
        except Exception: pass
        time.sleep(1)
    return False

def finish_status(mid, reply, alts=""):
    full = f"{reply}\n\n{alts}" if alts else reply
    if mid and len(full) <= 4000 and tg_stage_edit(mid, full):
        outbox_flush(); return
    tg_send_raw(reply)
    if alts: time.sleep(1); tg_send_raw(alts)

def tg_send(text):
    if tg_send_raw(text):
        outbox_flush(); return True
    outbox_add(text); return False

# =====================================================================
# 5. LLM CLIENT (AGNOSTIC)
# =====================================================================
def ask_llm(prompt, extra=""):
    return ask_llm_msgs([{"role": "user", "content": prompt}], extra)

def ask_llm_msgs(msgs, extra=""):
    if not budget_ok(): return json.dumps({"status": "FAILED", "reply": "Límite diario alcanzado."})
    inc_budget()
    first_user = next((m["content"] for m in msgs if m["role"] == "user"), "")
    facts = search_facts(first_user)
    stats = get_stats()["str"]
    sys_prompt = (
        f"Eres MicroBot v8 ({platform.system()}). Stats: {stats}. Memoria relevante: {json.dumps(facts, ensure_ascii=False)}.\n"
        f"Protocolo ReAct: piensas, ejecutas UNA acción, lees la OBSERVATION y decides de nuevo.\n"
        f"- Si necesitas datos del sistema: plan=[{{\"cmd\":\"UN solo comando\"}}] o search=\"query\".\n"
        f"- Cuando la observación alcanza para responder: sin plan ni search, escribe reply final.\n"
        f"- NUNCA repitas un mismo comando dentro de un turno; si falla, diagnostica con otro comando distinto.\n"
        f"- new_fact: guarda recetas reutilizables (problema → solución), no trivialidades.\n"
        f"Devuelve SOLO JSON:\n"
        f'{{"thought":"...","plan":[{{"cmd":"","expect":""}}],"search":"","new_fact":"",'
        f'"status":"SUCCESS|CONTINUE|FAILED","reply":"...","alternatives":[]}}'
        f"{extra}"
    )
    try:
        if "generativelanguage.googleapis.com" in CFG["base_url"]:
            url = f"{CFG['base_url']}/{CFG['model']}:generateContent?key={CFG['api_key']}"
            contents = [{"role": ("model" if m["role"] == "assistant" else "user"),
                         "parts": [{"text": m["content"]}]} for m in msgs]
            payload = {
                "contents": contents,
                "systemInstruction": {"parts": [{"text": sys_prompt}]}
            }
            res = requests.post(url, json=payload, timeout=60).json()
            raw = res["candidates"][0]["content"]["parts"][0]["text"]
        else:
            url = f"{CFG['base_url']}/chat/completions"
            h = {"Authorization": f"Bearer {CFG['api_key']}", "Content-Type": "application/json"}
            payload = {"model":CFG["model"],"messages":[{"role":"system","content":sys_prompt}] + msgs}
            res = requests.post(url, headers=h, json=payload, timeout=60).json()
            raw = res["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return m.group(0) if m else raw
    except Exception as e:
        err = str(e)
        if "429" in err or "Rate limit" in err or "'choices'" in err:
            return json.dumps({"status":"FAILED","reply":"⚠️ Límite diario de modelos gratuitos alcanzado. Intenta mañana o añade créditos en OpenRouter."})
        return json.dumps({"status":"FAILED","reply":f"Error LLM: {e}"})

def parse_json(s):
    try: return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        return json.loads(m.group(0)) if m else {}

# =====================================================================
# 6. WEB SEARCH (DUCKDUCKGO LITE)
# =====================================================================
def web_search(query):
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        snippets = re.findall(r'class="result__snippet">(.*?)</a>', r.text, re.DOTALL)
        titles = re.findall(r'class="result__url">(.*?)</a>', r.text, re.DOTALL)
        out = []
        for i in range(min(3, len(snippets))):
            t = html.unescape(re.sub(r"<.*?>", "", titles[i])).strip() if i < len(titles) else ""
            s = html.unescape(re.sub(r"<.*?>", "", snippets[i])).strip()
            out.append(f"• {t}: {s[:200]}")
        return "\n".join(out)[:600] or "(sin resultados)"
    except Exception as e: return f"[web error] {e}"

# =====================================================================
# 7. SKILLS
# =====================================================================
def install_skill(name, code, desc=""):
    ok, msg = validate_code(code)
    if not ok: return f"[SKILL RECHAZADA] {msg}"
    with db() as c:
        c.execute("INSERT OR REPLACE INTO skills (name, code, desc, ts) VALUES (?, ?, ?, ?)",
                  (name, code, desc, datetime.datetime.now().isoformat()))
        c.commit()
    return f"[SKILL GUARDADA] {name}"

def run_skill(name, arg=""):
    sk = db().execute("SELECT code FROM skills WHERE name=?", (name,)).fetchone()
    if not sk: return f"[SKILL NO EXISTE] {name}"
    try:
        ns = {}; exec(sk["code"], ns, ns)
        if "run" in ns: return ns["run"](arg)
        return "[SKILL SIN run()]"
    except Exception as e: return f"[SKILL ERROR] {e}"

def validate_code(code):
    if not code or not code.strip(): return False, "vacío"
    if len(code) > 120000: return False, "demasiado grande"
    try: ast.parse(code)
    except SyntaxError as e: return False, f"syntax: {e}"
    return True, "ok"

# =====================================================================
# 8. MISSION ENGINE
# =====================================================================
def execute_mission(goal):
    if not resources_ok():
        tg_send(f"[MISION PAUSA] Recursos bajos: {get_stats()['str']}"); return
    tg_send(f"🎯 Misión: {goal}\nMax {CFG['mission_max_steps']} pasos.")
    history = []
    for step in range(1, CFG["mission_max_steps"]+1):
        prompt = f"GOAL: {goal}\nSTEP {step}/{CFG['mission_max_steps']}\nHISTORY: {json.dumps(history, ensure_ascii=False)}"
        data = parse_json(ask_llm(prompt, "MODO MISION: devuelve plan mínimo, status SUCCESS/FAILED/NEEDS_HELP."))
        if data.get("new_fact"): add_fact(data["new_fact"])
        if data.get("search"):
            res = web_search(data["search"])
            history.append({"tool":"web","q":data["search"],"out":res[:300]})
            continue
        plan = data.get("plan", [])
        if plan:
            for p in plan:
                cmd = p.get("cmd","") if isinstance(p, dict) else str(p)
                out = run_cmd(cmd)
                history.append({"cmd":cmd,"out":out[:300]})
                tg_send(f"Paso {step} ⚙️ `{cmd}`\n{out[:600]}")
        status = (data.get("status") or "SUCCESS").upper()
        if status in ("SUCCESS","FAILED","NEEDS_HELP") or not plan:
            tg_send(f"[{status}] {data.get('reply','Misión finalizada.')}")
            break
        time.sleep(1)

# =====================================================================
# 9. COMMANDS ZERO-API
# =====================================================================
def dispatch(text, store=None):
    t = text.strip(); tl = t.lower()
    if tl == "/help":
        return True, ("🤖 *MicroBot v8 Universal*\n"
            "/status  /recursos  /mision <objetivo>  /skills  /restart\n"
            "/todo add|list|done  /nota set|get|list  /idea  /agenda\n"
            "Pipeline visible activo. Memoria FTS5.")
    if tl == "/status":
        return True, f"📊 {get_stats()['str']}\nHechos: {db().execute('SELECT COUNT(*) FROM facts').fetchone()[0]}"
    if tl == "/recursos":
        return True, get_stats()["str"]
    if tl == "/skills":
        rows = db().execute("SELECT name, desc FROM skills").fetchall()
        return True, "🧰 Skills:\n" + "\n".join(f"• {r['name']}: {r['desc']}" for r in rows) or "Sin skills."
    if tl == "/restart":
        tg_send("🔄 Reiniciando..."); os._exit(0)
    if tl == "/todo list":
        rows = db().execute("SELECT id, task FROM todos WHERE done=0").fetchall()
        return True, "📝 " + ("\n".join(f"[{r['id']}] ⬜ {r['task']}" for r in rows) or "vacía")
    if tl.startswith("/todo add "):
        task = t[10:].strip()
        db().execute("INSERT INTO todos (task, ts) VALUES (?, ?)", (task, datetime.datetime.now().isoformat())); db().commit()
        return True, f"📝 Guardada: {task}"
    if tl.startswith("/todo done "):
        arg = t[11:].strip()
        db().execute("UPDATE todos SET done=1 WHERE id=? OR task LIKE ?", (arg, f"%{arg}%")); db().commit()
        return True, f"✅ {arg}"
    if tl == "/nota list":
        rows = db().execute("SELECT key, value FROM notes").fetchall()
        return True, "📌 " + ("\n".join(f"• {r['key']}: {r['value']}" for r in rows) or "vacías")
    if tl.startswith("/nota set "):
        _, k, v = t.split(" ", 2)
        db().execute("INSERT OR REPLACE INTO notes (key, value, ts) VALUES (?, ?, ?)",
                     (k, v, datetime.datetime.now().isoformat())); db().commit()
        return True, f"📌 {k} guardada."
    if tl.startswith("/nota get "):
        k = t[10:].strip()
        r = db().execute("SELECT value FROM notes WHERE key=?", (k,)).fetchone()
        return True, f"📌 {k}: {r['value']}" if r else "No existe."
    if tl == "/ideas":
        rows = db().execute("SELECT idea, ts FROM ideas ORDER BY id DESC LIMIT 10").fetchall()
        return True, "💡 " + ("\n".join(f"• [{r['ts'][:10]}] {r['idea']}" for r in rows) or "vacías")
    if tl.startswith("/idea "):
        db().execute("INSERT INTO ideas (idea, ts) VALUES (?, ?)", (t[6:].strip(), datetime.datetime.now().isoformat())); db().commit()
        return True, "💡 Idea guardada."
    if tl == "/agenda":
        rows = db().execute("SELECT id, schedule_time, task, daily FROM schedules").fetchall()
        return True, "⏰ " + ("\n".join(f"[{r['id']}] ({'Diaria' if r['daily'] else 'Puntual'} {r['schedule_time']}): {r['task']}" for r in rows) or "vacía")
    return False, None

# =====================================================================
# 10. AGENT TURN (REACT: RAZONAR -> ACTUAR -> OBSERVAR, max N sub-pasos)
# =====================================================================
def _extract_action(data):
    """Primera acción pedida por el modelo: ("search", q) | ("cmd", c) | None."""
    if not isinstance(data, dict): return None
    if data.get("search"): return ("search", str(data["search"]).strip())
    plan = data.get("plan") or []
    if plan:
        p = plan[0]
        cmd = (p.get("cmd", "").strip() if isinstance(p, dict) else str(p).strip())
        if cmd: return ("cmd", cmd)
    return None

def _react_assistant_msg(thought, label):
    return {"role": "assistant", "content": json.dumps(
        {"thought": thought[:300], "action": label}, ensure_ascii=False)}

def handle_turn(text, progress=None):
    if not resources_ok():
        return f"[PAUSA RECURSOS] {get_stats()['str']}", ""
    max_steps = int(CFG.get("max_substeps", 3))
    msgs = [{"role": "user", "content": text}]
    tried = set()
    step = 0
    data = {}
    while True:
        if progress: progress("think")
        data = parse_json(ask_llm_msgs(msgs))
        if not isinstance(data, dict) or not data:
            if progress: progress("think")
            data = parse_json(ask_llm_msgs(msgs + [{"role": "user", "content": "(respuesta vacía; repetí SOLO el JSON)"}]))
            if not isinstance(data, dict) or not data:
                return "(sin respuesta del modelo)", ""
        action = _extract_action(data)
        if data.get("status") == "FAILED" or action is None:
            break                                   # concluyó (o se rindió): reply es la respuesta final
        if step >= max_steps:
            # Step Budget agotado: conclusión forzada, sin más acciones
            if progress: progress("think")
            msgs.append({"role": "user", "content":
                "LÍMITE DE PASOS INTERNOS alcanzado. Respondé AHORA tu conclusión final "
                "en JSON con reply (y new_fact si aprendiste una receta), sin plan ni search."})
            data2 = parse_json(ask_llm_msgs(msgs))
            if isinstance(data2, dict) and data2: data = data2
            break
        kind, payload = action
        if progress: progress("search" if kind == "search" else "exec")
        if kind == "cmd" and payload in tried:
            # Loop Guard: no re-ejecutar; exigir estrategia distinta o conclusión
            obs = ("OBSERVATION DEL SISTEMA: ya ejecutaste exactamente ese comando en este turno. "
                   "NO lo repitas. Cambiá de enfoque con otro comando distinto, o devolvé tu "
                   "conclusión final sin plan.")
        elif kind == "search":
            obs = web_search(payload)[:800]
            tried.add(payload)
        else:
            obs = run_cmd(payload)[:800]
            tried.add(payload)
        msgs.append(_react_assistant_msg(data.get("thought", ""), f"{kind}: {payload}"))
        msgs.append({"role": "user", "content": f"OBSERVATION:\n{obs}"})
        step += 1
    if data.get("new_fact"): add_fact(data["new_fact"])
    add_history(text, (data.get("reply") or "")[:2000])
    reply = (data.get("reply") or "").strip() or "(sin respuesta del modelo)"
    alts = data.get("alternatives") or []
    alts_str = "\n".join(f"{i+1}. {a}" for i, a in enumerate(alts[:CFG.get("max_alternatives", 2)]))
    return reply, (f"\n🤖 *Variantes:*\n{alts_str}" if alts_str else "")

# =====================================================================
# 11. DAEMONS
# =====================================================================
def auto_worker():
    while True:
        time.sleep(300)
        if not budget_ok() or not resources_ok(): continue
        data = parse_json(ask_llm("Hacé una micro-tarea de mantenimiento: limpieza, backup, nota útil."))
        if data.get("plan"): handle_turn("auto-mantenimiento")

def compressor():
    while True:
        now = datetime.datetime.now()
        if now.hour == 4 and now.minute < 5:
            with db() as c:
                c.execute("DELETE FROM facts WHERE id NOT IN (SELECT MIN(id) FROM facts GROUP BY fact)")
                c.execute("VACUUM"); c.commit()
        time.sleep(60)

def scheduler():
    while True:
        now = datetime.datetime.now()
        hm = now.strftime("%H:%M")
        today = datetime.date.today().isoformat()
        with db() as c:
            for r in c.execute("SELECT * FROM schedules").fetchall():
                fire = (r["daily"] and r["schedule_time"] == hm and r["last_run"] != today) or \
                       (not r["daily"] and r["schedule_time"] == now.strftime("%Y-%m-%d %H:%M"))
                if fire:
                    if r["daily"]: c.execute("UPDATE schedules SET last_run=? WHERE id=?", (today, r["id"]))
                    else: c.execute("DELETE FROM schedules WHERE id=?", (r["id"],))
                    c.commit()
                    tg_send(f"⏰ {r['task']}")
                    if any(w in r["task"].lower() for w in ["saluda","revisa","reporte","limpia","optimiza"]):
                        threading.Thread(target=lambda: handle_turn(r["task"]), daemon=True).start()
        time.sleep(30)

# =====================================================================
# 12. TELEGRAM DAEMON (PIPELINE VISIBLE)
# =====================================================================
def telegram_daemon():
    lock = InstanceLock(); lock.acquire()
    threading.Thread(target=auto_worker, daemon=True).start()
    threading.Thread(target=compressor, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    tg_send(f"🚀 MicroBot v8.0 Online\n{get_stats()['str']}\nPipeline visible. /help")
    offset = 0
    try:
        while True:
            try:
                r = requests.get(f"https://api.telegram.org/bot{CFG['telegram_token']}/getUpdates",
                    params={"offset": offset+1, "timeout": 30}, timeout=35).json()
                for u in r.get("result", []):
                    offset = u["update_id"]
                    m = u.get("message", {})
                    if str(m.get("chat",{}).get("id")) != CFG["chat_id"]: continue
                    txt = (m.get("text") or "").strip()
                    if not txt: continue
                    stop = threading.Event()
                    def typ(): 
                        while not stop.wait(4.5): tg_action()
                    threading.Thread(target=typ, daemon=True).start()
                    mid = tg_stage_send(STAGE["recv"])
                    def stage(name): 
                        if mid: tg_stage_edit(mid, STAGE.get(name, ""))
                    try:
                        handled, out = dispatch(txt)
                        if handled:
                            finish_status(mid, out); continue
                        reply, alts = handle_turn(txt, progress=stage)
                        finish_status(mid, reply, alts)
                    finally:
                        stop.set()
            except Exception:
                time.sleep(3)
    finally:
        lock.release()

# =====================================================================
# 13. CLI
# =====================================================================
def cli():
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
    print(f"MicroBot v8 ({OS_NAME}) — límites: {CFG['max_calls_day']}/día | /help")
    while True:
        try: txt = input("\n[microbot] > ").strip()
        except (EOFError, KeyboardInterrupt): break
        if not txt or txt.lower() in ("salir","exit","quit"): break
        h, o = dispatch(txt)
        if h: print(o); continue
        r, a = handle_turn(txt, progress=lambda n: print(f"  · {STAGE.get(n,'')}", flush=True))
        print(r)
        if a: print(a)

# =====================================================================
# ENTRY
# =====================================================================
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--daemon","-d"):
        telegram_daemon()
    elif len(sys.argv) > 1 and sys.argv[1] == "--status":
        print(get_stats()["str"])
    elif len(sys.argv) > 1 and sys.argv[1] == "--test":
        import tempfile
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(__file__))
        print("Harness inline not implemented, run test_harness.py")
    else:
        # one-shot query
        txt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
        if txt:
            r, a = handle_turn(txt, progress=lambda n: print(f"  · {STAGE.get(n,'')}", flush=True))
            print(r)
            if a: print(a)
        else:
            cli()