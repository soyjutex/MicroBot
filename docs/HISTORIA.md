# Historia de MicroBot

> Cómo una notebook vieja de 2 GB de RAM terminó corriendo un agente autónomo
> multiplataforma en un solo archivo. Cronología real del proyecto (2026).

---

## Fase 0 — El punto de partida

Una Compaq Pentium Dual T3200 (2 núcleos, 2 GB RAM, Debian 13) acumulaba
experimentos fallidos: Docker con un contenedor de n8n que el hardware no
podía sostener, y un bot viejo con un servicio systemd que lo **resucitaba
solo** cada vez que se lo mataba. Primera lección: matar el proceso no basta;
hay que desactivar el servicio.

## Fase 1 — Acceso remoto serio

Clave SSH Ed25519 desde Windows. A partir de ahí, todo el mantenimiento es
reproducible por línea de comandos.

## Fase 2 — Diagnóstico

Inventario honesto: servicios duplicados, contenedores al pedo, basura en disco.
Resultado: limpieza total y una sola cosa corriendo.

## Fase 3 — v1 → v3: el núcleo

- **v1**: fusión de dos scripts en uno. Memoria JSON persistente
  (hechos + historial + presupuesto diario), lock de instancia única,
  bloqueo regex de comandos destructivos.
- **v2**: aprendizaje de errores — tabla de errores persistente, circuit
  breaker (>50% errores → pausa automática), backoff exponencial, alertas
  de presupuesto al 70/90%.
- **v3**: planes multi-paso en JSON, skills Python persistentes validadas con
  `compile()` + test automático, critic loop (segunda llamada que analiza
  fallos del plan), scratchpad estilo ReAct.

## Fase 4 — v4 "Optimus": consciencia de hardware

- Misiones (`/mision`): bucle agente con tope de pasos y corte anti-bucle,
  estados explícitos (`completada`, `necesita_ayuda`, `sin_presupuesto`...).
- Telemetría propia leída de `/proc` (nunca `top`: pesado).
- Guardia `resources_ok()`: si la RAM libre cae, el bot se pausa solo.
- **zram** en el host: ~3 GB de swap comprimido en RAM. La mejora #1 para
  esta máquina.

## Fase 5 — Permisos con whitelist

Una misión real chocó contra "Permiso denegado" y quemó pasos reintentando.
Solución: whitelist sudo mínima (`lsof`, `needrestart`,
`systemctl restart microbot`) + regla en el system prompt: si algo requiere
root fuera de la whitelist, responder con el comando exacto y no reintentar.
Prueba end-to-end: misión relanzada, completada en 1 paso usando sudo sin
password solo donde corresponde.

## Fase 6 — v7 "MicroBot": identidad propia

- Renaming total, un único `bot.py` como servicio systemd, symlink limpio.
- **Multi-proveedor agnóstico**: OpenRouter, Groq, Gemini u Ollama local
  cambian con `base_url`; auth solo si hay key; fallback de modelos.
- **Dashboard** propio en stdlib puro (:8080): CPU/RAM/disco/temp reales
  + estado del bot, cero dependencias.

## Fase 7 — v7.1: memoria semántica y búsqueda

- **SQLite + FTS5**: los hechos relevantes se seleccionan semánticamente
  por turno (~700 chars), fallback a LIKE.
- **Búsqueda web quirúrgica**: el modelo puede pedir `"search"` una vez;
  resultados recortados a 3 fuentes / 600 chars y una sola pasada final.
- **Compresión nocturna**: a las 04:00 consolida hechos redundantes con
  backup previo. Probado en vivo: 20 hechos → 11 sin pérdida.
- Comandos locales sin costo de API: `/nota /notas /idea /ideas`.

## Fase 8 — v7.1.1: resiliencia de red

Diagnóstico con datos reales: la red era intermitente y los envíos fallaban
en silencio. Solución: reintentos con log + **outbox persistente** — todo
mensaje no entregado se guarda en SQLite y sale en el próximo envío exitoso.

## Fase 9 — v7.2: pipeline visible

Nada de "cargando..." fingido: burbuja nativa de tipeo mientras trabaja y un
único mensaje que se edita mostrando la capa real
(`recibido → pensando → web → shell → critic`) hasta convertirse en la
respuesta final.

## Fase 10 — MicroBot-X: multiplataforma

Mismo cerebro, nueva PAL: telemetría nativa de Windows (`GetSystemTimes`,
`GlobalMemoryStatusEx`), PowerShell como shell de planes, lock con
`msvcrt.locking`. Probado en hardware real de escritorio con dos instancias
paralelas (Linux + Windows) usando tokens separados.

---

## Filosofía aprendida en el camino

1. **El hardware límite enseña mejor diseño**: cada byte de RAM obligó a
   recortar prompts, ventanas de contexto y dependencias.
2. **Un archivo gana**: instalar = copiar. Debuggear = leer de arriba a abajo.
3. **Los estados deben ser verdaderos**: si dice "ejecutando", está ejecutando.
4. **Toda red falla**: reintentos + outbox o silencio eterno.
5. **Presupuesto cerrado = tranquilidad**: el agente nunca puede gastar más
   de lo permitido, ni el LLM ni la misión más ambiciosa.
6. **Permisos explícitos**: whitelist corta y regla de "no reintentes lo
   denegado" evita bucles costosos.
