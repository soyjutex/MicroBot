#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MicroBot v7.0.0 - Agente autonomo de administracion de sistemas para Telegram.

Caracteristicas principales:
    - Cerebro LLM (OpenRouter Free, costo cero) con protocolo JSON estricto: piensa, planifica, ejecuta, critica y aprende.
    - Multi-respuesta: ademas de la respuesta principal, ofrece hasta N alternativas.
    - Memoria persistente unificada en SQLite (facts, historial, errores, misiones, skills).
    - Misiones multi-paso con corte anti-bucle y pausa ante falta de permisos.
    - Skills Python reutilizables con validacion sintactica y test automatico.
    - Presupuesto diario de llamadas API + circuit breaker anti-cascada de errores.
    - Consciencia de hardware: auto-pausa si la RAM o la carga estan en limites.

Seguridad:
    - Las credenciales viven en config.json (chmod 600), NUNCA en el codigo.
    - Lista BLOCKED: comandos destructivos rechazados antes de ejecutarse.
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
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

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


def now_iso():
    """Timestamp ISO local, usado en toda la memoria."""
    return datetime.datetime.now().isoformat()


PID_FILE = "/tmp/microbot.pid"
SELF_FILE = os.path.abspath(__file__)

# Comandos que MicroBot nunca ejecuta, ni siquiera como root.
BLOCKED = [
    r"rm\s+-rf\s+/\b",
    r"mkfs",
    r"dd\s+if=",
    r":\(\)\s*\{\s*:\|\:&\s*;\s*\}",   # fork bomb
    r"shutdown",
    r"reboot",
    r"halt",
    r">\s*/dev/sd",
    r"chmod\s+-R\s+777\s+/\b",
]

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

    # --- clave/valor (estado simple: usage, auto, breaker...) ---------------
    def get(self, key, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        self.conn.commit()

    # --- facts ---------------------------------------------------------------
    def add_fact(self, text):
        self.conn.execute("INSERT INTO facts (ts, text) VALUES (?, ?)", (now_iso(), text[:500]))
        self.conn.commit()

    def facts(self, limit=15):
        rows = self.conn.execute("SELECT text FROM facts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [r[0] for r in reversed(rows)]

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
# === 4. ESTADISTICAS DE SISTEMA ==============================================
# ==============================================================================

def get_sys_stats():
    """Lee load, RAM y temperatura SIN procesos pesados (solo /proc y /sys)."""
    stats = {"load1": 0.0, "ram_free": 0, "ram_total": 0, "temp": "?"}
    try:
        stats["load1"] = float(open("/proc/loadavg").read().split()[0])
    except Exception:
        pass
    try:
        mi = {}
        for line in open("/proc/meminfo"):
            k, _, v = line.partition(":")
            mi[k.strip()] = int(v.strip().split()[0])
        stats["ram_free"] = mi.get("MemAvailable", 0) // 1024
        stats["ram_total"] = mi.get("MemTotal", 0) // 1024
    except Exception:
        pass
    try:
        stats["temp"] = f"{int(open('/sys/class/thermal/thermal_zone0/temp').read().strip()) / 1000:.0f}C"
    except Exception:
        pass
    stats["str"] = (f"load={stats['load1']} ram={stats['ram_free']}MB libres "
                    f"de {stats['ram_total']}MB temp={stats['temp']}")
    return stats


def resources_ok():
    s = get_sys_stats()
    return s["ram_free"] >= CFG["ram_min_mb"] and s["load1"] <= CFG["load_max"]


# ==============================================================================
# === 5. EJECUCION DE COMANDOS ================================================
# ==============================================================================

def run_cmd(cmd):
    """Ejecuta un comando bash con guarda anti-destructivos y timeout."""
    for pat in BLOCKED:
        if re.search(pat, cmd):
            return "[BLOQUEADO] comando peligroso rechazado"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=CFG["cmd_timeout_sec"])
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
    """Envia mensaje al chat autorizado. Silencia errores de red (nunca tumba el daemon)."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{CFG['telegram_token']}/sendMessage",
            json={"chat_id": CFG["chat_id"], "text": text[:4000]},
            timeout=15,
        )
    except Exception:
        pass


def notify(text):
    print(text)
    tg_send(text)


# ==============================================================================
# === 7. CLIENTE LLM (OPENROUTER / GEMINI) ====================================


def call_openrouter(prompt, system_instruction):
    """OpenRouter: API compatible OpenAI. El router 'openrouter/free' rota modelos
    gratuitos; si alguno falla o devuelve vacio, se reintenta con un free fijo."""
    for model in (CFG["model"], "nvidia/nemotron-3.5-lightning:free"):
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {CFG['api_key']}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/soyjutex/MicroBot",
                "X-Title": "MicroBot",
            }
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


def build_system_prompt(store, system_extra=""):
    """Construye la instruccion de sistema completa con todo el contexto del bot."""
    context = (
        f"HARDWARE REAL: Pentium Dual T3200 2GHz, 2GB RAM, HDD. Stats ahora: {get_sys_stats()['str']}. "
        f"NUNCA propongas tareas pesadas si hay pocos recursos. "
        f"MEMORIA (facts): {json.dumps(store.facts(15), ensure_ascii=False)}. "
        f"HISTORIAL RECIENTE: {json.dumps(store.recent_history(5), ensure_ascii=False)}. "
        f"ERRORES RECIENTES: {json.dumps(store.recent_errors(5), ensure_ascii=False)}. "
        f"SCRATCHPAD: {json.dumps(store.recent_scratch(8), ensure_ascii=False)}"
    )
    max_alt = CFG["max_alternatives"]
    return (
        f"Eres MicroBot, admin L4 autonomo de compacserver (Debian 13), ciclo cerrado "
        f"PENSAR-ACTUAR-OBSERVAR-APRENDER. Corres como root en una notebook dedicada exclusivamente a ti, "
        f"pero mantenes la lista BLOCKED de comandos destructivos por seguridad propia. {context}. "
        f"MULTI-RESPUESTA: ademas del campo reply (respuesta principal clara y directa), genera hasta {max_alt} "
        f"alternativas utiles en 'alternatives': pueden ser otra forma de resolverlo, una sugerencia extra "
        f"de mantenimiento, o un dato relacionado valioso. Si no aportan valor real, dejalo vacio []. "
        f"MISION_PROTOCOL: 1.ANALIZA 2.EJECUTA 3.OBSERVA 4.CRITICA 5.APRENDE. "
        f"status=SUCCESS cuando la tarea quedo resuelta; FAILED si es imposible; CONTINUE si falta iterar. "
        f"Para charla simple responde directo con status SUCCESS y sin plan (ahorra llamadas). "
        f"Responde SIEMPRE JSON exacto: {{"
        f"\"thought\": \"razonamiento breve\", "
        f"\"plan\": [{{\"cmd\": \"bash\", \"expect\": \"esperado\"}}], "
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
        return call_llm(user_input, build_system_prompt(store, system_extra))
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


def handle_turn(user_input, store):
    """
    Procesa un turno completo de conversacion.
    Devuelve (respuesta_principal, alternativas_formateadas).
    """
    raw = ask_llm(user_input, store)
    data = parse_json_loose(raw) or {"plan": [], "reply": "", "alternatives": []}
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
            results, ok = exec_plan(plan, store)
            for r in results:
                failed = ("BLOQUEADO" in r["out"] or "TIMEOUT" in r["out"])
                em = "❌" if failed else "⚙️"
                out.append(f"{em} {r['cmd']}\n{r['out']}")
            if not ok:
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

def auto_worker(store):
    """Hilo de auto-mejora: cada N segundos hace UN ciclo util si hay presupuesto y recursos."""
    while True:
        time.sleep(CFG["auto_interval_sec"])
        try:
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


def acquire_lock():
    """Garantiza instancia unica via PID lock."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            print(f"microbot ya corriendo (pid {pid}).", file=sys.stderr)
            sys.exit(1)
        except (ProcessLookupError, ValueError, PermissionError):
            pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def release_lock():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def telegram_daemon():
    store = Store(DB_FILE)
    acquire_lock()
    threading.Thread(target=auto_worker, args=(store,), daemon=True).start()
    tg_send(f"MicroBot v7.0.0 online.\n{get_sys_stats()['str']}\nMulti-respuesta activa. /help")
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
                    kind, out = dispatch(text, store)
                    if kind is True:
                        if out == RESTART_SENTINEL:
                            do_restart()
                        else:
                            tg_send(out)
                        continue
                    if kind == "mision":
                        executor.submit(run_mission, store, out)
                        continue
                    reply, alts = handle_turn(text, store)
                    tg_send(reply)
                    if alts:
                        time.sleep(1)   # evita flood-limit al mandar dos mensajes seguidos
                        tg_send(alts)
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
    store = Store(DB_FILE)
    if len(sys.argv) == 1:
        print(f"MicroBot v7 - misiones + planes + skills + critic + multi-respuesta. "
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
            kind, out = dispatch(text, store)
            if kind is True:
                print(out)
                continue
            if kind == "mision":
                run_mission(store, out)
                continue
            reply, alts = handle_turn(text, store)
            print(reply)
            if alts:
                print("\n" + alts)
        return

    arg = " ".join(sys.argv[1:])
    if arg in ("--daemon", "-d"):
        telegram_daemon()
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
        reply, alts = handle_turn(arg, store)
        print(reply)
        if alts:
            print("\n" + alts)


if __name__ == "__main__":
    cli()
