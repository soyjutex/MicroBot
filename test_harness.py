#!/usr/bin/env python3
"""Harness offline — 17 checks, sin red ni API."""
import os, sys, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot

RES = []

def chk(name, fn):
    try:
        fn()
        RES.append((name, True, ""))
        print(f"  [OK] {name}")
    except Exception as e:
        RES.append((name, False, str(e)))
        print(f"  [FAIL] {name}: {e}")

# PAL
def t_telemetry():
    t = bot._telemetry()
    assert isinstance(t, dict) and t["ram_total_mb"] > 0

def t_get_stats():
    s = bot.get_stats()
    assert "RAM=" in s["str"]

def t_resources_ok():
    assert isinstance(bot.resources_ok(), bool)

# SECURITY
def t_blocked():
    bad = "format c:" if bot.IS_WINDOWS else "rm -rf /"
    assert "[BLOQUEADO]" in bot.run_cmd(bad)

def t_run_cmd():
    assert "hola" in bot.run_cmd("echo hola")

# DB / FTS5
def t_store_roundtrip():
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    bot.DB_FILE = db
    bot.init_db()
    bot.kv_set("k", {"n": 1})
    assert bot.kv_get("k")["n"] == 1

def t_fts():
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    bot.DB_FILE = db
    bot.init_db()
    bot.add_fact("La impresora es Epson LX-350")
    facts = bot.search_facts("impresora taller")
    assert any("Epson" in f for f in facts)

def t_history():
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    bot.DB_FILE = db
    bot.init_db()
    bot.add_history("p", "r")
    row = bot.db().execute("SELECT user, bot FROM history ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(row) == ("p", "r")

# BUDGET / OUTBOX
def t_budget():
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    bot.DB_FILE = db; bot.CFG["max_calls_day"] = 1
    bot.init_db()
    assert bot.budget_ok()
    bot.inc_budget()
    assert not bot.budget_ok()

def t_outbox():
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    bot.DB_FILE = db; bot.init_db()
    bot.outbox_add("test")
    rows = bot.db().execute("SELECT text FROM outbox").fetchall()
    assert len(rows) == 1

# JSON / PARSE
def t_parse_fences():
    raw = '```json\n{"reply":"ok","status":"SUCCESS"}\n```'
    assert bot.parse_json(raw)["reply"] == "ok"

def t_parse_prose():
    raw = 'Claro! {"reply":"hi","status":"SUCCESS"} espero sirva'
    assert bot.parse_json(raw)["reply"] == "hi"

# STAGE MESSAGES
def t_stages():
    assert set(bot.STAGE.keys()) >= {"recv","think","search","exec"}

# REACT HELPERS
def t_react_action():
    assert bot._extract_action({"plan":[{"cmd":"ls -la"}]}) == ("cmd", "ls -la")
    assert bot._extract_action({"plan":["free -m"]}) == ("cmd", "free -m")
    assert bot._extract_action({"search":"kernel debian 13"}) == ("search", "kernel debian 13")
    assert bot._extract_action({"reply":"listo"}) is None
    assert bot._extract_action({"plan":[{"cmd":""}]}) is None
    assert bot._extract_action({"plan":[{"cmd":" a "},{"cmd":"b"}]}) == ("cmd", "a")

def t_react_msg():
    m = bot._react_assistant_msg("pensando X", "cmd: free -m")
    assert m["role"] == "assistant"
    d = json.loads(m["content"])
    assert d["thought"] == "pensando X" and d["action"] == "cmd: free -m"

# SKILLS
def t_skill():
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    bot.DB_FILE = db; bot.init_db()
    code = "def run(arg):\n    return (arg or '').upper()\n"
    assert "GUARDADA" in bot.install_skill("mayus", code)
    assert "HOLA" in bot.run_skill("mayus", "hola")

def t_validate_bad():
    ok, _ = bot.validate_code("esto no es python ((((")
    assert not ok

# LOCK
def t_lock():
    import io
    old = bot.PID_FILE
    bot.PID_FILE = os.path.join(tempfile.mkdtemp(), "lock.pid")
    old_err = sys.stderr; sys.stderr = io.StringIO()
    try:
        l1 = bot.InstanceLock(); l1.acquire()
        try:
            bot.InstanceLock().acquire()
            raise AssertionError("debe fallar")
        except SystemExit: pass
        finally: l1.release()
    finally:
        sys.stderr = sys.__stderr__; bot.PID_FILE = old

if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass
    so = "Windows" if bot.IS_WINDOWS else ("macOS" if bot.IS_MACOS else "Linux")
    print(f"HARNESS MicroBot v8 sobre {so}")
    print("-"*50)
    for n, f in sorted([(n, f) for n, f in globals().items() if n.startswith("t_")], key=lambda x: x[0]):
        chk(n[2:], f)
    print("-"*50)
    ok = sum(1 for _, p, _ in RES if p)
    print(f"{ok}/{len(RES)} passed | {so}")
    sys.exit(0 if ok == len(RES) else 1)