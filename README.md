# 🤖 MicroBot

> **Autonomous Edge AI Agent & Linux SysAdmin in a single Python file.**
> *Zero-bloat. Self-healing. Built for low-spec hardware (~22MB RAM footprint).*

Agente autónomo de administración de sistemas que vive en una notebook vieja convertida en servidor Linux dedicado. Se lo habla por **Telegram** o por **terminal**, entiende lenguaje natural vía **OpenRouter (tier Free)**, ejecuta comandos Linux, aprende de sus errores y mantiene memoria persistente. **Todo el proyecto corre con costo cero: $0 en APIs, $0 en infraestructura.**

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
- **Memoria persistente unificada** en SQLite: facts, historial, errores, misiones, skills y preferencias.
- **Skills Python reutilizables**: el bot puede crear funciones propias, validadas con `ast.parse` y testeadas automáticamente antes de guardarse.
- **Presupuesto diario** de llamadas API con alertas al 70%/90% y circuit breaker anti-cascada de errores.
- **Consciencia de hardware**: lee `/proc` y temperatura; se auto-pausa si la RAM baja o la carga sube (ideal para hardware humilde).
- **Seguridad por capas**: credenciales fuera del código (`config.json`, chmod 600), lista `BLOCKED` de comandos destructivos, único chat autorizado, instancia única por PID lock.

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

> ¿Prefieres correrlo como usuario normal sin root? Cambia `User=root` por tu usuario en `install/microbot.service` antes de instalar. El bot funciona igual; solo perderá acceso a operaciones de sistema protegidas.

## Uso

**Terminal:**
```bash
microbot                        # chat interactivo
microbot "cuánta RAM libre?"    # consulta puntual (responde + variantes)
microbot --status               # presupuesto y estado del breaker
```

**Dentro del chat interactivo / Telegram:**
```
/help /status /recursos /memoria /errors /skills /misiones
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
│   ├── dashboard.html
│   └── stats_collector.py
└── docs/                   # historia, protocolos de mantenimiento y bitácoras
```

En runtime (servidor):
```
/opt/microbot/
├── bot.py                  # código
├── config.json             # credenciales (chmod 600, nunca en git)
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

- [`docs/HISTORIA.md`](docs/HISTORIA.md) — cronología completa del proyecto, problemas encontrados y decisiones de diseño.
- [`docs/PROTOCOLO_MANTENIMIENTO.md`](docs/PROTOCOLO_MANTENIMIENTO.md) — cómo desplegar cambios sin romper nada.
- [`docs/BITACORA_Y_OPTIMIZACION.md`](docs/BITACORA_Y_OPTIMIZACION.md) — lecciones aprendidas y reglas de operación.
- [`docs/BITACORA_EVOLUCION.md`](docs/BITACORA_EVOLUCION.md) — evolución v1→v6.
- [`docs/PROTOCOL_RAPIDO.md`](docs/PROTOCOL_RAPIDO.md) — patrones de operación rápida.

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
