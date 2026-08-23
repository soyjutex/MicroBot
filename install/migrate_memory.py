#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Migrador de memoria: unifica los datos viejos en la nueva base SQLite.

Fuentes soportadas:
    1. ~/.bot_memory.json          (formato NEXUS v5)
    2. ~/.nexus_brain.db           (formato MicroBotOS v6, tabla memory key-value)

Destino:
    data/microbot.db               (schema v7, ver clase Store en bot.py)

Uso:
    python3 migrate_memory.py [destino.db] [json_viejo] [sqlite_viejo]
Todos los argumentos son opcionales; los defaults sirven para instalacion tipica.
Idempotente: puede correrse varias veces sin duplicar facts (chequea existencia).
"""

import json
import os
import sqlite3
import sys

HOME = os.path.expanduser("~")
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "microbot.db")

NEW_DB = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
OLD_JSON = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HOME, ".bot_memory.json")
OLD_SQLITE = sys.argv[3] if len(sys.argv) > 3 else os.path.join(HOME, ".nexus_brain.db")


def ensure_schema(conn):
    conn.executescript("""
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
            label TEXT, cmd TEXT, out TEXT);
        CREATE TABLE IF NOT EXISTS skills (
            name TEXT PRIMARY KEY,
            code TEXT NOT NULL,
            desc TEXT DEFAULT '',
            created TEXT NOT NULL);
    """)
    conn.commit()


def fact_exists(conn, text):
    row = conn.execute("SELECT 1 FROM facts WHERE text=? LIMIT 1", (text[:500],)).fetchone()
    return row is not None


def migrate_json(conn):
    """Migra ~/.bot_memory.json (v5): facts, history, errors, skills."""
    if not os.path.exists(OLD_JSON):
        print(f"  [skip] {OLD_JSON} no existe")
        return
    with open(OLD_JSON, "r", encoding="utf-8") as f:
        m = json.load(f)

    now = "2026-01-01T00:00:00"
    n_facts = 0
    for fact in m.get("facts", []):
        if isinstance(fact, str) and fact.strip() and not fact_exists(conn, fact):
            conn.execute("INSERT INTO facts (ts, text) VALUES (?, ?)", (now, fact[:500]))
            n_facts += 1

    n_hist = 0
    if conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0:
        for h in m.get("history", [])[-40:]:
            conn.execute("INSERT INTO history (ts, user, assistant) VALUES (?, ?, ?)",
                         (now, str(h.get("user", ""))[:500], str(h.get("assistant", ""))[:500]))
            n_hist += 1

    n_errs = 0
    if conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0] == 0:
        for e in m.get("errors", []):
            conn.execute("INSERT INTO errors (ts, ctx, err) VALUES (?, ?, ?)",
                         (e.get("ts", now), str(e.get("ctx", ""))[:200], str(e.get("err", ""))[:300]))
            n_errs += 1

    n_sk = 0
    for name, sk in m.get("skills", {}).items():
        conn.execute("INSERT OR REPLACE INTO skills (name, code, desc, created) VALUES (?, ?, ?, ?)",
                     (name, sk.get("code", ""), sk.get("desc", "")[:200], sk.get("created", now)))
        n_sk += 1

    # Estado simple que vale la pena preservar
    conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('auto', ?)",
                 (json.dumps(m.get("auto", False)),))
    conn.commit()
    print(f"  [ok] JSON: {n_facts} facts, {n_hist} history, {n_errs} errors, {n_sk} skills")


def migrate_old_sqlite(conn):
    """Migra ~/.nexus_brain.db (v6): tabla memory key-value -> kv + facts si aplica."""
    if not os.path.exists(OLD_SQLITE):
        print(f"  [skip] {OLD_SQLITE} no existe")
        return
    old = sqlite3.connect(OLD_SQLITE)
    try:
        rows = old.execute("SELECT key, value FROM memory").fetchall()
    except sqlite3.OperationalError:
        print("  [skip] tabla memory no existe en DB vieja")
        return

    n_kv = 0
    for k, v in rows:
        # Las claves de preferencias del usuario se preservan tal cual en kv.
        conn.execute("INSERT OR IGNORE INTO kv (key, value) VALUES (?, ?)", (f"legacy_{k}", v))
        n_kv += 1
    conn.commit()
    old.close()
    print(f"  [ok] SQLite viejo: {n_kv} claves migradas como legacy_*")


def main():
    os.makedirs(os.path.dirname(NEW_DB), exist_ok=True)
    conn = sqlite3.connect(NEW_DB)
    ensure_schema(conn)
    print(f"Migrando hacia {NEW_DB}:")
    migrate_json(conn)
    migrate_old_sqlite(conn)
    total_facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    total_kv = conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
    conn.close()
    print(f"Listo. Base unificada: {total_facts} facts, {total_kv} claves kv.")


if __name__ == "__main__":
    sys.exit(main())
