# MicroBot

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey.svg)]
[![RAM Idle](https://img.shields.io/badge/RAM_idle-~40MB-brightgreen.svg)]
[![Tests](https://img.shields.io/badge/offline_tests-20%2F20-success.svg)]

> **Agente autónomo de administración de sistemas en un solo archivo Python.**
> Un `bot.py` idéntico para Linux, Windows y macOS. Pensado desde cero para hardware humilde.

MicroBot es un agente que vive en tu máquina: lo hablás por **Telegram** o por **terminal**,
entiende lenguaje natural vía un LLM (Google Gemini o cualquier API compatible con OpenAI),
ejecuta comandos reales del sistema, guarda lo que aprende en memoria semántica propia y
responde mostrando cada capa del razonamiento.

```
vos ──Telegram/CLI──> MicroBot ──> ciclo ReAct (max 3 sub-pasos)
                                     │
   ┌─────────────────────────────────┤
   │  🧠 THINK   el LLM decide en JSON: actuar o responder
   │  ⚙️ ACT     UN comando / UNA búsqueda web
   │  👁️ OBSERVE la salida vuelve al LLM en privado (el usuario no ve errores crudos)
   └──> repite o concluye ──> reply final + receta aprendida si aplica
```

## Por qué existe

La mayoría de los frameworks de agentes (LangChain, AutoGen, CrewAI...) exigen cientos de
dependencias y máquinas con recursos de sobra. MicroBot es la apuesta contraria:

- **Un solo archivo**: todo el agente es `bot.py`. Lo copiás, lo corés.
- **Cero bloat**: una sola dependencia externa (`requests`). Todo lo demás es stdlib.
- **Hardware humilde**: ~40MB de RAM. Probado en un Pentium del 2008 con Debian 13.
- **Universal por diseño**: la capa PAL (Platform Abstraction Layer) detecta el OS al
  arrancar — telemetría nativa (`/proc` en Linux, `ctypes`+WMI en Windows), bash o
  PowerShell como shell de planes, lock de instancia por API nativa de cada sistema.

## Características

- **Ciclo ReAct con auto-corrección**: el bot no es un pipeline lineal. Razona, ejecuta UN comando,
  lee la observación en privado y decide de nuevo (hasta 3 micro-pasos por turno). Si un comando
  falla, diagnostica con otro distinto antes de hablarte — vos solo recibís la conclusión.
- **Loop Guard**: si intenta repetir un mismo comando dentro del turno, el sistema se lo impide
  y le exige cambiar de estrategia o concluir. Inmune a bucles infinitos.
- **Pipeline visible**: cada mensaje muestra su progreso real por capas
  (`recibido → pensando → ejecutando`) editando el mismo mensaje de Telegram. No es un
  fake loading: es el estado verdadero del agente.
- **Aprendizaje procedimental**: no guarda trivialidades. Cuando resuelve algo no trivial,
  sintetiza una receta reutilizable (problema → solución) que la búsqueda FTS5 recupera
  en turnos futuros.
- **Protocolo JSON estricto**: el LLM responde thought + plan de comandos + búsqueda web +
  hecho nuevo + status. Parsing tolerante (acepta fences markdown y JSON embebido en prosa).
- **Guarda anti-destructivos**: lista negra de comandos (`rm -rf /`, `mkfs`, `dd`, `format`,
  `diskpart`...) validada antes de ejecutar nada.
- **Presupuesto diario**: coto configurable de llamadas LLM por día con aviso al agotarse.
- **Outbox persistente**: si Telegram falla, los mensajes quedan en cola y se reintentan.
- **Skills Python**: el bot puede escribir funciones propias, validarlas con `ast.parse`
  y testearlas antes de guardarlas para reutilizarlas.
- **Comandos zero-API**: `/status`, `/recursos`, `/todo`, `/nota`, `/idea`, `/agenda`,
  `/skills`, `/help` funcionan sin gastar presupuesto del LLM.
- **Lock de instancia**: imposible correr dos daemons sobre la misma base de datos.

## Instalación rápida (Debian/Ubuntu)

```bash
git clone https://github.com/soyjutex/MicroBot.git
cd MicroBot
cp config.example.json config.json   # completá tus credenciales
sudo bash install/install.sh
```

El instalador corre el harness offline, instala el servicio systemd y deja el comando
global `microbot` en el PATH.

### En Windows

No hay servicio: corré el daemon oculto con

```powershell
Start-Process pythonw -ArgumentList "bot.py","--daemon" -WindowStyle Hidden
```

y guardá ese comando como tarea programada "Al iniciar sesión" si querés auto-arranque.

## Configuración

Copiá `config.example.json` a `config.json` (junto a `bot.py` o en `~/.microbot/`):

| Clave | Descripción |
|---|---|
| `api_key` | Tu API key (Gemini u OpenRouter) |
| `base_url` | Endpoint de la API |
| `model` | Modelo a usar |
| `telegram_token` | Token del bot de Telegram (@BotFather) |
| `chat_id` | Tu chat ID (único chat autorizado) |
| `max_calls_day` | Presupuesto diario de llamadas LLM |
| `max_substeps` | Micro-pasos ReAct por turno (default 3) |

## Uso

```bash
microbot --status                  # telemetría del host sin gastar API
microbot "cuánta ram libre hay"    # consulta one-shot
microbot                           # modo interactivo
python3 bot.py --daemon            # daemon Telegram (systemd lo hace solo)
python3 test_harness.py            # 16 pruebas offline, sin red ni API key
```

Por Telegram: hablale en lenguaje natural. `/help` lista los comandos locales.

## Arquitectura (30 segundos)

```
bot.py (~650 líneas)
├── PAL          telemetría, run_cmd, lock de instancia (por OS)
├── BRAIN        SQLite + FTS5: facts, history, kv, skills, outbox, budget
├── TELEGRAM     core con pipeline visible (typing + edición por capas)
├── LLM          cliente agnóstico (Gemini native / OpenAI-compatible)
├── REACT LOOP   razonar → actuar → observar, loop guard, step budget
├── SKILLS       código Python validado con ast + test automático
├── MISSIONS     bucle multi-paso con corte anti-bucle
├── COMMANDS     dispatch zero-API (/status, /todo, ...)
└── DAEMONS      auto-worker, compresor nocturno, scheduler
```

## Licencia

MIT — hacé lo que quieras, no hay garantía.
