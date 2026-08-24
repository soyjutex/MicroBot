# 🤖 MicroBot

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey.svg)]
[![RAM Footprint](https://img.shields.io/badge/RAM_Idle-~40MB-brightgreen.svg)]
[![Monthly Cost](https://img.shields.io/badge/Cost-%240%2Fmonth-success.svg)]
[![Hardware](https://img.shields.io/badge/Tested_on-Pentium_2008-orange.svg)]

> **Autonomous Edge AI Agent & SysAdmin in a single Python file — Linux, Windows y macOS.**
> *Zero-bloat. Self-healing. Built for low-spec hardware (~40MB RAM footprint).*

Agente autónomo de administración de sistemas **multiplataforma**: un único `bot.py` idéntico para cualquier OS (la PAL detecta el sistema al arrancar: telemetría nativa, bash o PowerShell como shell de planes, lock de instancia por OS). Se lo habla por **Telegram** o por **terminal**, entiende lenguaje natural vía **OpenRouter (tier Free)**, ejecuta comandos reales del sistema, aprende de sus errores y mantiene memoria persistente semántica. **Todo el proyecto corre con costo cero: $0 en APIs, $0 en infraestructura.**

Incluye `test_harness.py`: batería de pruebas offline (17 checks) que valida PAL, memoria FTS5, seguridad y protocolo en cualquier OS sin red ni API.

## v8 UNIVERSAL
Hasta v7 el bot era Linux-only; desde **v8.0** el mismo archivo corre en Windows y macOS con todas las capacidades (misiones, critic, skills, compresión nocturna, outbox, pipeline visible). Verificado con 17/17 pruebas en Debian 13 y Windows 10 sobre el mismo código.

```
[tú] ──Telegram──> MicroBot ──> OpenRouter/free (piensa + planifica en JSON)
                                  │
                                  ├──> ejecuta comandos (con guarda anti-destructivos)
                                  ├──> critica resultados y aprende hechos nuevos
                                  └──> responde + ofrece variantes (multi-respuesta)
```

## Características

- **Ciclo cerrado**: PENSAR → ACTUAR → OBSERVAR → CRITICAR → APRENDER en cada turno.
- **Multi-respuesta**: además de la respuesta principal, genera hasta 2 variantes útiles (otra forma de resolverlo, sugerencia de mantenimiento, dato relacionado).
- **Misiones multi-paso**: `/mision <objetivo>` lanza un bucle agente con corte anti-bucle y pausa inteligente ante falta de permisos o recursos.
- **Memoria persistente unificada** en SQLite con **búsqueda semántica FTS5**: cada turno inyecta al LLM solo los 3-5 hechos relevantes al mensaje (zero-token bloat), no todo el historial.
- **Búsqueda web quirúrgica**: el modelo puede pedir búsquedas reales (DuckDuckGo Lite) con coto duro de 3 resultados / 600 caracteres anti-explosión de tokens.
- **Compresión nocturna**: a las 04:00 consolida hechos duplicados u obsoletos con UNA llamada LLM, con backup previo automático (nada se pierde).
- **Skills Python reutilizables**: el bot puede crear funciones propias, validadas con `ast.parse` y testeadas automáticamente antes de guardarse.
- **Presupuesto diario** de llamadas API con alertas al 70%/90% y circuit breaker anti-cascada de errores.
- **Consciencia de hardware**: lee `/proc` y temperatura; se auto-pausa si la RAM baja o la carga sube (ideal para hardware humilde).
- **Seguridad por capas**: credenciales fuera del código (`config.json`, chmod 600), lista `BLOCKED` de comandos destructivos, único chat autorizado, instancia única por PID lock.

### 🥊 ¿Por qué MicroBot vs Otros Frameworks?

| Característica | MicroBot | AutoGPT / CrewAI / LangChain |
| :--- | :---: | :---: |
| **Consumo de RAM** | **~22 MB** | 400 MB - 2 GB+ |
| **Complejidad** | **1 script Python** | Docenas de dependencias y Docker |
| **Hardware mínimo** | **Pentium 2008 / 512MB RAM** | CPUs modernas / 8GB+ RAM |
| **Costo Operativo** | **$0.00 / mes** | Requiere planes pagos o APIs costosas |
| **Curva de instalación** | **1 comando (`install.sh`)** | Alta (Entornos virtuales, contenedores) |

### 📸 Capturas

> *GIF de una `/mision` ejecutándose paso a paso y respuesta con variantes — [pendiente capturar desde Telegram].*
> Mientras tanto podés ver el dashboard en vivo: `http://IP-DEL-SERVIDOR:8080` (CPU/RAM/temp + memoria del bot).

## Requisitos

- Debian/Ubuntu (probado en Debian 13, Python 3.13) — cualquier Linux moderno sirve
- Python 3.10+
- Una API key de [OpenRouter](https://openrouter.ai/keys) — **gratis, sin tarjeta de crédito** (modelo `openrouter/free`)
- Un bot de Telegram ([@BotFather](https://t.me/BotFather)) y tu chat ID

## Instalación rápida

```bash
git clone https://github.com/soyjutex/MicroBot.git
cd MicroBot

# 1. Configurar credenciales
cp config.example.json config.json
nano config.json          # completa api_key (OpenRouter), telegram_token y chat_id

# 2. Instalar como servicio root (caja dedicada)
sudo bash install/install.sh
```

El instalador: copia el código a `/opt/microbot/`, migra memoria vieja si existe (`~/.bot_memory.json` o `~/.nexus_brain.db`), instala el servicio systemd **root** (`microbot.service`) y crea el comando global `microbot`.

> **¿Sin systemd?** (macOS, BSD, contenedores, servidores sin root) Ejecución directa en background:
> ```bash
> nohup python3 bot.py --daemon > /dev/null 2>&1 &
> ```

### 🔌 Multi-proveedor LLM (agnóstico)

MicroBot funciona con **cualquier API compatible OpenAI** — solo cambiás `base_url` y `model` en `config.json`, sin tocar código:

| Proveedor | `base_url` | `model` |
|---|---|---|
| OpenRouter (gratis, default) | `https://openrouter.ai/api/v1` | `openrouter/free` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Ollama local (sin key) | `http://localhost:11434/v1` | `llama3.2` |
| Gemini directo | — | `provider: "gemini"` |

### 🔐 Configuración por variables de entorno

Toda clave de `config.json` puede sobreescribirse con variables de entorno `MICROBOT_*` — ideal para Docker, Kubernetes o VPS efímeros:

```bash
MICROBOT_API_KEY=sk-or-v1-... \
MICROBOT_TELEGRAM_TOKEN=123:abc \
MICROBOT_CHAT_ID=456 \
python3 bot.py --daemon
```

## Uso

**Terminal:**
```bash
microbot                        # chat interactivo
microbot "cuánta RAM libre?"    # consulta puntual (responde + variantes)
microbot --status               # presupuesto y estado del breaker
microbot --compactar            # fuerza la compresión de memoria (lo mismo que hace a las 04:00)
```

**Dentro del chat interactivo / Telegram:**
```
/help /status /recursos /memoria /errors /skills /misiones
/nota <texto> /notas /idea <texto> /ideas    # notas locales, zero-API
/mision <objetivo>           # tarea multi-paso con bucle agente
/skill save|test|run|del <nombre>
/auto on|off                 # bucle de auto-mejora cada 30 min
/stopauto /resetauto /restart
```

**Operación:**
```bash
systemctl status microbot       # estado del servicio
journalctl -u microbot -f       # logs en vivo
```

**Dashboard:** abrí `http://IP-DEL-SERVIDOR:8080` — CPU/RAM/disco/temperatura en vivo, memoria del bot (hechos, conversaciones, errores, skills) y cola del log. Solo lectura, sin frameworks, datos reales de SQLite y `/proc`.

## Multi-respuesta (v7)

Cuando respondemos algo, MicroBot devuelve su respuesta principal y hasta 2 alternativas:

```
> ¿cómo está el servidor?

RAM 1497MB libres de 1905MB, load 0.07, disco al 3%. Todo normal.

🤖 Variantes:
1. Si querés puedo programar un reporte diario automático con /auto on.
2. El disco está casi vacío; buen momento para hacer backup de configuraciones.
```

Las variantes son opcionales para el modelo: solo aparecen cuando aportan valor real.

## Estructura del proyecto

```
├── bot.py                  # código completo del agente (una sola fuente)
├── config.example.json     # plantilla de configuración (sin secretos)
├── requirements.txt        # única dependencia: requests
├── install/
│   ├── install.sh          # instalador (systemd root + migración)
│   ├── microbot.service    # unidad systemd
│   └── migrate_memory.py   # migrador JSON+SQLite-viejo → SQLite v7
├── dashboard/              # dashboard web simple (CPU/RAM/temp/logs)
│   ├── dashboard.html      # interfaz (HTML+CSS+JS puro, sin frameworks)
│   └── server.py           # servidor stdlib de solo lectura, puerto 8080
└── docs/                   # arquitectura, historia y guía de operación
```

En runtime (servidor):
```
/opt/microbot/
├── bot.py                  # código
├── config.json             # credenciales (chmod 600, nunca en git)
├── dashboard/              # dashboard web (servido en :8080)
└── data/
    ├── microbot.db         # memoria SQLite unificada
    └── microbot.log        # log propio
```

## Diseño de seguridad

| Capa | Mecanismo |
|---|---|
| Secretos | `config.json` chmod 600, excluido por `.gitignore`, override por variables de entorno `MICROBOT_*` |
| Comandos | Regex `BLOCKED`: `rm -rf /`, `mkfs`, `dd`, fork-bomb, `shutdown`, etc. |
 | Acceso | Un único `chat_id` autorizado en Telegram |
| Instancia | PID lock en `/tmp/microbot.pid` |
| Presupuesto | Límite diario de llamadas + circuit breaker con backoff exponencial |
| Recursos | Auto-pausa si RAM < 150MB o load > 4 |

## Documentación

- [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) — cómo funciona por dentro: flujo, protocolo JSON, memoria FTS5, presupuesto y seguridad.
- [`docs/HISTORIA.md`](docs/HISTORIA.md) — cronología completa: cómo creció de script a agente autónomo multiplataforma.
- [`docs/OPERACION.md`](docs/OPERACION.md) — instalación, actualización, backups y diagnóstico rápido.

## Hardware de origen

Este proyecto nació y corre en una Compaq del 2008: Pentium Dual T3200 @ 2GHz, 2GB RAM (+2.9GB zram), HDD 160GB, Debian 13 (Trixie). Por eso el diseño es obsesivo con recursos: sin Docker, sin modelos locales, sin frameworks — solo Python + requests + SQLite.

### 📊 Benchmark real (compacserver)

| Métrica | Valor |
|---|---|
| CPU | Intel Pentium Dual T3200 @ 2.00GHz (2008) |
| RAM en idle (proceso completo) | **~22MB** |
| RAM del equipo | 2GB DDR2 + zram activo |
| SO | Debian GNU/Linux 13 (Trixie) |
| LLM | OpenRouter Free (`openrouter/free`) |
| Costo mensual | **$0** |

## Costo total del proyecto: $0

| Componente | Servicio | Costo |
|---|---|---|
| Cerebro LLM | OpenRouter tier Free (`openrouter/free`) | $0 |
| Infraestructura | Notebook reciclada del 2008 | $0 |
| Interfaz | Bot de Telegram | $0 |
| Memoria / datos | SQLite local | $0 |
| Monitoreo | Dashboard propio en Python stdlib | $0 |

Ninguna parte de la cadena tiene costo mensual: el hardware es reciclado, el LLM usa los endpoints gratuitos de OpenRouter y todo lo demás es software propio corriendo en la misma máquina.

## Licencia

MIT
