# Arquitectura de MicroBot

> Un agente autónomo en un solo archivo Python. Diseñado para hardware mínimo,
> sin frameworks, sin colas, sin base de datos externa. Solo stdlib + `requests`.

---

## Principios de diseño

| Principio | Consecuencia práctica |
|---|---|
| **Un archivo** | Todo el agente vive en `bot.py`. Copiar = instalar. |
| **Stdlib primero** | La única dependencia externa es `requests` (HTTP). |
| **Presupuesto cerrado** | Límite duro de llamadas LLM por día. Nada puede excederlo. |
| **Memoria como SQLite** | Una tabla KV + FTS5 para búsqueda semántica. Cero servicios. |
| **Falla sin morir** | Toda red/LLM/shell está envuelta: reintentos, timeout y log. |
| **Seguridad por defecto** | Regex de comandos destructivos, lock de instancia única, whitelist explícita. |

---

## Flujo general

```
Telegram ──► getUpdates (long-polling 30s)
                │
                ▼
        ┌───────────────┐   /comando local ──► dispatch() ──► respuesta inmediata (sin API)
        │ telegram_daemon│
        └───────┬───────┘
                │ texto libre
                ▼
          handle_turn()
                │
     ┌──────────┼──────────────────────────┐
     ▼          ▼                          ▼
 memoria    ask_llm()                  web_search()
 (FTS5 +    protocolo JSON             (solo si el modelo
  hechos     {reply, plan,              la pide; tope duro
  relevantes status, new_fact,           3 resultados / 600 chars)
  telemetría search, alternatives})
     │          │
     │          ▼
     │      exec_plan() ──► shell nativa del OS ──► salida recortada
     │          │
     │          ▼ (si el plan falla)
     │      critic_loop(): segunda llamada que diagnostica y corrige
     │
     ▼
 respuesta editada sobre el mensaje de estado (pipeline visible)
```

---

## El protocolo JSON (contrato con el modelo)

Cada llamada al LLM exige una respuesta JSON estricta:

```json
{
  "status": "SUCCESS | CONTINUE | FAILED",
  "reply": "texto para el usuario",
  "plan": [{"cmd": "uptime"}, {"cmd": "df -h /"}],
  "search": "consulta web opcional",
  "new_fact": "dato durable opcional",
  "alternatives": ["variante 1", "variante 2"]
}
```

Reglas que vive en el system prompt:

- **Pregunta ≠ acción**: si preguntan algo, responder no es ejecutar comandos.
- Máximo 3 pasos por plan; cada paso tiene `expect` implícito y corta ante error.
- Si falta permiso, responder `needs_help` con el comando exacto (no reintentar).
- `thought` interno ≤ 2 líneas antes del JSON (estilo Hermes, bounded).

El parser (`parse_json_loose`) tolera cercos de código y texto alrededor:
los modelos free no siempre obedecen el formato perfecto.

---

## Memoria (SQLite + FTS5)

```
kv           → presupuesto diario, usage, outbox, backups, config dinámica
facts        → hechos durables (una línea cada uno)
facts_fts    → índice FTS5 sobre facts: búsqueda semántica barata
history      → conversación reciente (ventana corta al prompt)
errors       → aprendizaje de errores + circuit breaker
missions     → registro de misiones con estados
scratchpad   → últimos pasos ejecutados (inyectado al prompt, estilo ReAct)
skills       → funciones Python validadas con compile()/ast.parse + test
```

- Cada turno inyecta los 3-5 hechos más relevantes según FTS5 (~700 chars máx),
  con fallback a LIKE en SQLite sin FTS5.
- **Compresión nocturna** (04:00): consolida facts redundantes con backup previo
  guardado en `kv`. Prohibido inventar: solo fusionar/eliminar duplicados.
  Manual: `python3 bot.py --compactar`.

---

## Presupuesto y autocontrol

- Contador de llamadas por día en `kv.usage`; tope configurable (default 45).
- Alertas al 70% y 90%.
- **Circuit breaker**: >50% de errores automáticos en 1h → pausa de 1h (backoff hasta 24h).
- **Guardia de recursos** (`resources_ok()`): RAM libre mínima y CPU máxima;
  si no se cumple, ciclos automáticos y misiones se pausan solos.

---

## Pipeline visible (v7.2)

Feedback honesto de dónde está el turno, sin mensajes falsos:

1. Al recibir: burbuja nativa `sendChatAction(typing)` refrescada cada 4.5 s.
2. Un único mensaje de estado que se **edita** por capa real:
   `📨 recibido → 🧠 pensando → 🌐 web → ⚙️ shell → 🔧 critic`.
3. Al terminar, ese mensaje **se convierte en la respuesta** (cero basura extra).

Si la red falla a mitad de camino: reintentos + **outbox** en SQLite
(la respuesta pendiente se entrega en el próximo envío exitoso).

---

## Multiplataforma (MicroBot-X)

La Capa de Abstracción de Plataforma (PAL) detecta el OS al arrancar:

| Subsistema | Linux | Windows |
|---|---|---|
| Telemetría CPU/RAM | `/proc`, `/sys` | `GetSystemTimes`, `GlobalMemoryStatusEx` |
| Shell de planes | bash | PowerShell |
| Lock de instancia | `fcntl.flock` | `msvcrt.locking` |
| Servicios | systemd | Task Scheduler / NSSM |

El resto (memoria, protocolo, presupuesto, ciclo agente) es idéntico.

---

## Seguridad

- Chat ID autorizado único: mensajes de otros chats se ignoran.
- Bloqueo regex de comandos destructivos (`rm -rf /`, `format`, `mkfs`, etc.).
- En Linux, el bot corre con whitelist sudo explícita y mínima
  (`lsof`, `needrestart`, `systemctl restart microbot`) — nada más.
- Lock de instancia única: nunca dos daemons peleando por `getUpdates`
  (un token de bot = exactamente una instancia).
- Secretos solo en `config.json` local (gitignoreado); jamás en el repo.
