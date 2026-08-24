#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Harness de pruebas OFFLINE para MicroBot v8.0 universal.

No usa red ni API: valida PAL, memoria, seguridad y utilidades en CUALQUIER OS.
Uso:  python test_harness.py        (junto a bot.py)
Sale con codigo 0 si todo pasa, 1 si algo falla.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot  # noqa: E402


RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print(f"  [OK]   {name}")
    except Exception as e:
        RESULTS.append((name, False, str(e)))
        print(f"  [FALLO] {name}: {e}")


# --- 1. PAL -----------------------------------------------------------------

def test_telemetry():
    t = bot.telemetry()
    assert isinstance(t, dict), "telemetry no devolvio dict"
    assert t["ram_total_mb"] and t["ram_total_mb"] > 0, "sin RAM total"
    assert t["ram_free_mb"] is not None, "sin RAM libre"


def test_get_sys_stats_str():
    s = bot.get_sys_stats()
    assert s["str"] and "ram=" in s["str"], f"str raro: {s['str']}"


def test_host_identity():
    host, os_name, cpu = bot.host_identity()
    assert host and os_name and cpu, f"identidad incompleta: {(host, os_name, cpu)}"


def test_resources_ok():
    assert isinstance(bot.resources_ok(), bool)


# --- 2. Seguridad -----------------------------------------------------------

def test_blocked_current_os():
    malo = "format c: /x" if bot.IS_WINDOWS else "rm -rf /"
    out = bot.run_cmd(malo)
    assert "[BLOQUEADO]" in out, f"comando destructivo NO bloqueado: {out[:80]}"


def test_run_cmd_safe():
    out = bot.run_cmd("echo hola-microbot")
    assert "hola-microbot" in out, f"echo no funciono: {out[:120]}"


def test_timeout_guard():
    assert bot.CFG["cmd_timeout_sec"] > 0


# --- 3. Memoria -------------------------------------------------------------

def test_store_roundtrip():
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    st = bot.Store(db)
    st.set("prueba", {"n": 42, "lista": [1, 2]})
    assert st.get("prueba")["n"] == 42
    assert st.get("inexistente", "default") == "default"


def test_fts_semantic():
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    st = bot.Store(db)
    st.add_fact("La impresora del taller se llama Epson LX-350")
    hechos = st.relevant_facts("como se llama la impresora del taller")
    assert any("Epson" in h for h in hechos), f"FTS5 no encontro el hecho: {hechos}"


def test_history():
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    st = bot.Store(db)
    st.add_history("pregunta test", "respuesta test")
    row = st.conn.execute(
        "SELECT user, assistant FROM history ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(row) == ("pregunta test", "respuesta test"), f"row={tuple(row)}"


# --- 4. Protocolo LLM --------------------------------------------------------

def test_parse_json_loose_fences():
    raw = 'Aca va:\n```json\n{"reply": "hi", "plan": [], "status": "SUCCESS"}\n```'
    d = bot.parse_json_loose(raw)
    assert d and d["reply"] == "hi"


def test_parse_json_loose_prosa():
    raw = 'Claro! {"reply":"listo","status":"SUCCESS","plan":[]} espero sirva'
    d = bot.parse_json_loose(raw)
    assert d and d["reply"] == "listo"


def test_stage_messages():
    claves = {"recv", "think", "search", "exec"}
    assert claves.issubset(bot.STAGE_MSG.keys()), "faltan etapas del pipeline"
    assert callable(bot.cli_progress)


# --- 5. Skills ----------------------------------------------------------------

def test_skills_roundtrip():
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    st = bot.Store(db)
    codigo = "def run(arg):\n    return (arg or '').upper()\n"
    bot.install_skill(st, "mayus", codigo, "pasa a mayusculas")
    salida = bot.run_skill(st, "mayus", "hola")
    assert "HOLA" in salida, f"skill no corrio: {salida[:80]}"


def test_validate_code_rechaza_mal_codigo():
    ok, motivo = bot.validate_code("esto no es python valido ((((")
    assert not ok and motivo, f"valido codigo roto: ok={ok}"


def test_validate_code_acepta_buen_codigo():
    ok, _ = bot.validate_code("def run(arg):\n    return arg\n")
    assert ok


# --- 6. Lock de instancia unica ----------------------------------------------

def test_lock_segundo_adquierre_falla():
    viejo = bot.PID_FILE
    bot.PID_FILE = os.path.join(tempfile.mkdtemp(), "harness.pid")
    import io
    viejo_err = sys.stderr
    sys.stderr = io.StringIO()
    try:
        l1 = bot.InstanceLock()
        l1.acquire()                       # primer lock: debe entrar
        try:
            bot.InstanceLock().acquire()   # segundo lock: debe morir
            raise AssertionError("un segundo lock NO deberia poder adquirirse")
        except SystemExit:
            pass
        finally:
            l1.release()
    finally:
        sys.stderr = viejo_err
        bot.PID_FILE = viejo


# --- Runner -------------------------------------------------------------------

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    so = "Windows" if bot.IS_WINDOWS else ("macOS" if bot.IS_MAC else "Linux")
    print(f"HARNESS MicroBot v8.0 sobre {so}")
    print("-" * 50)
    for nombre, fn in sorted(
            ((n, f) for n, f in globals().items()
             if n.startswith("test_") and callable(f)),
            key=lambda x: x[0]):
        check(nombre.replace("test_", ""), fn)
    print("-" * 50)
    ok = sum(1 for _, paso, _ in RESULTS if paso)
    print(f"{ok}/{len(RESULTS)} pruebas pasaron | plataforma: {so}")
    sys.exit(0 if ok == len(RESULTS) else 1)
