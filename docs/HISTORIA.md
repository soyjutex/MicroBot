# HISTORIA COMPLETA — Proyecto bot en compacserver
## Todo lo que hicimos, cómo lo hicimos, y limitaciones del hardware

---

## PARTE 1: QUÉ ES ESTE PROYECTO

**compacserver** = notebook vieja (Compaq) convertida en servidor Linux casero que corre un único agente autónomo llamado **bot**.

El bot:
- Se le habla por **terminal** (comando `bot`) o por **Telegram** (@Jutexcompacbot)
- Entiende lenguaje natural vía **Gemini 3.1 Flash-Lite**
- Ejecuta comandos Linux por el usuario (con bloqueo de comandos destructivos)
- Tiene **memoria persistente**: hechos, historial, errores y skills Python reutilizables
- Trabaja en **bucles de auto-mejora** con límites estrictos para no quemar tokens de Google

---

## PARTE 2: CRONOLOGÍA DE LO QUE HICIMOS (2026-08-22)

### Fase 0 — Punto de partida
- Windows con `smart_agent.py` (CLI con memoria, sin Telegram) en `G:\jutex@compacserver\`
- Notebook con `~/tg_agent.py` corriendo como ROOT (servicio systemd `tg_agent.service`)
- Basura acumulada: Docker + contenedor n8n + `~/opencode/docker-compose.yml` (intento fallido, hardware no daba)

### Fase 1 — Acceso SSH sin contraseña desde Windows
```
# En Windows (PowerShell):
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\id_ed25519" -N '""' -C "opencode-agent"
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" | ssh jutex@192.168.x.x "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
# pidió contraseña (redactada por seguridad) una última vez
```
Clave usada: Ed25519 (moderna, corta, segura). A partir de acá yo (el asistente) podía ejecutar todo por `ssh -o BatchMode=yes`.

### Fase 2 — Diagnóstico del sistema
- `systemctl list-units` → encontró `tg_agent.service` (root) que RESUCITABA el bot viejo cada vez que lo mataban
- `docker ps -a` → n8n corriendo al pedo
- Lección clave: matar el proceso no bastaba, había que **disablear el servicio systemd**

### Fase 3 — Bot unificado v1 → v2 → v3

**v1**: merge de smart_agent.py + tg_agent.py
- Memoria persistente (`~/.bot_memory.json`): facts + history + usage diario
- Límites: 120 calls Gemini/día, 6 ciclos auto/día
- Single-instance: lock por PID en `/tmp/bot.pid`
- Bloqueo regex de comandos destructivos
- Deploy: `~/bot.py`, symlink `~/.local/bin/bot`, PATH en `.bashrc`/`.profile`
- Servicio: `~/.config/systemd/user/bot.service` + `loginctl enable-linger jutex`

**v2**: aprendizaje de errores
- `errors[]` persistente con timestamp+contexto
- **Circuit breaker**: >50% errores auto en 1h → pausa 1h
- Backoff exponencial (base 1h, máx 24h)
- Alertas de presupuesto al 70% y 90%
- Migración de memoria con `setdefault` (para no romper memorias viejas)

**v3** (actual): planes + skills + critic
- **Planes multi-paso**: JSON `{"plan": [{"cmd":"...", "expect":"..."}]}` — ejecuta pasos secuenciales, corta ante error
- **Skills Python persistentes**: funciones guardadas en memoria con validación sintáctica (`compile()`) + test automático. El bot ya NO crea archivos .sh/.py sueltos.
- **Critic loop**: segunda llamada post-plan que analiza qué falló y puede proponer `new_skill`. Ya se auto-guardó una skill él solo (`safe_file_injection`: "usar heredocs con EOF entre comillas").
- **Scratchpad**: últimos pasos ejecutados inyectados al prompt (estilo ReAct)
- Comandos locales `/xxx` NO gastan API (dispatch local)

### Fase 4 — Limpieza total
```
docker stop n8n && docker rm n8n && docker rmi <imagen> && docker system prune -af
rm -rf ~/opencode
systemctl stop tg_agent.service && systemctl disable tg_agent.service   # via su con pty
pkill -9 -f tg_agent
rm ~/tg_agent.py ~/kill_*.py ~/test_tg.py etc.
```
Resultado: disco 3.1G/144G, solo bot.py + memoria + servicio user.

### Fase 5 — v4 Optimus + zram (2026-08-22, tarde)

**v4 "Optimus"**: misiones + consciencia de hardware (merge de ideas de un draft externo con nuestra base v3)
- `/mision <objetivo>`: bucle agente con MISSION_MAX_STEPS=6, corte anti-bucle, estados (`completada`, `necesita_ayuda`, `cortada_por_limite`, `sin_presupuesto`, `recursos_bajos`), registro en `missions[]` y comando `/misiones`
- `get_sys_stats()`: lee `/proc/loadavg` + `/proc/meminfo` + temperatura thermal_zone0 (SIN usar `top` que es pesado) e inyecta stats en cada prompt
- Guardia `resources_ok()`: RAM libre >= 150MB y load <= 4.0; si no, auto-ciclos y misiones se pausan solos
- Validación de patch/skills con `ast.parse`
- `/restart` seguro: sale limpio (release lock) y systemd lo revive — NO os.execv dentro del daemon
- Correcciones al draft externo: presupuesto diario aplica a misiones, mismo modelo 3.1-flash-lite, misma memoria, conservado todo v3
- Fix: captura de stdout en test_skill con contextlib; `--status` reconectado a dispatch

**zram instalado por el usuario (con root)**:
```bash
sudo apt update && sudo apt install zram-tools
```
Resultado verificado: módulo zram cargado, `/dev/zram0`, swap **2.9Gi comprimidos en RAM**, servicio `zramswap` activo. Para esta máquina de 2GB RAM es la mejora #1 de rendimiento.

### Problemas técnicos que tuvimos y cómo los resolvimos

| Problema | Solución |
|---|---|
| PowerShell no soporta `&&` | usar `;` o llamadas separadas |
| Heredoc remoto rompe comillas de Python | escribir archivo localmente y `scp` |
| `su -c` pide password interactiva por SSH | script Python con `pty.fork()` que alimenta la contraseña (scp + correr) |
| El bot viejo revivía solo | era systemd root service → disablearlo |
| Memoria v1 sin claves nuevas de v2/v3 | `load_memory()` hace `setdefault` de defaults |
| `/skill run X` fallaba si run() tenía firma distinta | try/except TypeError + captura de stdout con contextlib |
| Modelo creaba .sh/.py sueltos en vez de skills | instrucción explícita en system prompt + parseo de `new_skill` en handle_turn |

---

### Fase 6 — Sudo con whitelist para el bot (2026-08-22)

**Problema**: misión de procesos fantasma (`lsof /proc/*/fd`) falló: leer FDs de procesos ajenos requiere root. El bot quemó 4 pasos reintentando contra "Permiso denegado".

**Solución en dos partes**:

1. **Whitelist sudo** (instalada como root via su automatizado con pty, script `/tmp/root_setup.sh`):
```bash
apt-get install -y sudo lsof needrestart
echo 'jutex ALL=(root) NOPASSWD: /usr/bin/lsof, /usr/bin/needrestart, /usr/sbin/needrestart, /usr/bin/systemctl restart *, /bin/systemctl restart *' > /etc/sudoers.d/jutex-bot
chmod 440 /etc/sudoers.d/jutex-bot
```
Verificado: `sudo -n lsof` OK sin password; `sudo -n whoami` y `apt` correctamente RECHAZADOS (piden password).

2. **Bot actualizado**:
   - System prompt le declara su whitelist exacta y le prohíbe reintentar comandos denegados no-whitelisteados (debe responder `needs_help` con el comando root exacto)
   - Detección temprana en misiones: si la salida contiene "Permiso denegado/Permission denied" y el comando no era sudo → pausa inmediata, informa el comando root a correr y estado `falta_permiso_root` en `/misiones`
   - tg_send internos de misiones cambiados a notify() para ver progreso también por CLI

**Prueba end-to-end post-fix**: misión de ghost files relanzada — usó `sudo lsof +L1` sin password, diagnóstico correcto (no había archivos retenidos), `[MISION COMPLETADA]` en 1 paso.

---

## PARTE 3: ARQUITECTURA ACTUAL

```
Windows (G:\jutex@compacserver\)          compacserver (jutex@192.168.x.x)
├── bot.py        ← copia maestra         ├── ~/bot.py            ← el bot (única fuente en runtime)
└── Readme.txt                            ├── ~/.bot_memory.json   ← memoria persistente
                                          ├── ~/.local/bin/bot     ← symlink a ~/bot.py
                                          ├── ~/.config/systemd/user/bot.service
                                          └── ~/HISTORIA.txt       ← este doc (versión compacta)

Flujo: Telegram getUpdates (polling 30s) ─┐
                                          ├──> handle_turn() ──> ask_llm (Gemini) ──> exec_plan() ──> run_cmd()
Terminal: bot / bot "msg" ────────────────┘                          └──> critic_loop() ──> save_skill()
Auto-loop (thread, cada 30min si auto=on) ──> auto_cycle()
```

### Protocolo de respuesta del LLM (JSON obligatorio)
```json
{
  "plan": [{"cmd": "bash", "expect": "qué espero"}],
  "reply": "respuesta breve al usuario",
  "new_fact": "dato permanente opcional",
  "new_skill": {"name": "...", "code": "def run(arg=\"\")...", "desc": "..."}
}
```

### Estructura de memoria (~/.bot_memory.json)
```json
{
  "facts": [],           // conocimiento permanente
  "history": [],         // últimos 40 turnos
  "usage": {"date": "...", "calls": 0, "auto_cycles": 0},   // presupuesto diario
  "auto": false,         // modo bucle on/off
  "errors": [],          // últimos 50 errores con contexto
  "circuit_open": false, // breaker activado
  "backoff_until": 0,    // timestamp hasta cuándo pausado
  "skills": {},          // código Python reutilizable con test
  "scratchpad": []       // pasos recientes (ReAct)
}
```

---

## PARTE 4: LIMITACIONES DEL HARDWARE Y DEL DISEÑO (importante para evolucionar)

### Hardware real (medido)
| Componente | Detalle | Implicación |
|---|---|---|
| CPU | Intel Pentium Dual T3200 @ 2GHz (2008), 2 cores, sin HT, x86_64 | Sin AVX/AVX2 → imposible correr modelos locales modernos (llama.cpp, whisper, embeddings). Cualquier IA = API externa sí o sí |
| RAM | 1.9 GB total (~1.5 GB disponible) | No hay espacio para modelos locales ni para muchos contenedores. Docker fue removido también por esto. Un solo servicio Python liviano es lo máximo |
| Disco | HDD WDC WD1600BEVT 149GB (5400rpm, ~2008) | I/O lento: evitar logs gigantes, rotar journal, no bases de datos pesadas |
| Red | WiFi (wls1/wpa_supplicant) | Latencia variable; polling de Telegram OK pero webhooks requerirían IP fija/puerto expuesto (no recomendado) |
| SO | Debian 13 trixie (soportado hasta ~2030) | Bien por ahora; Python 3.13 actual |

### Limitaciones de diseño actuales (conocidas)
1. **API Key y token de Telegram hardcodeados** en bot.py — el usuario decidió ignorar este riesgo. Si se filtra el archivo, alguien gasta sus tokens.
2. **Un solo chat autorizado** (redactado por seguridad) — no multiusuario, no grupos.
3. **Sin confirmación humana** antes de comandos no-bloqueados: el modelo puede ejecutar cualquier comando no-listado en BLOCKED (ej: borrar archivos de home). Mitigación parcial: corre como jutex, no root.
4. **Polling, no webhooks** — delay de hasta 30s en respuestas.
5. **Memoria sin deduplicación** — facts pueden repetirse con el tiempo; history se trunca a 40.
6. **Skills sin sandbox real** — `exec()` corre con los permisos del proceso; una skill maliciosa generada por el modelo podría hacer daño a nivel usuario.
7. **Critic loop gasta calls extra** — cada plan consume 2 llamadas (agente + critic).
8. **getUpdates con offset simple** — si dos instancias corrigen (no debería por PID lock), se roban updates.

### Caminos de evolución futuros (ordenados por valor/costo)
1. **Rotar credenciales** y moverlas a variables de entorno o archivo 600 fuera del repo (30 min)
2. **Dedup de facts + resumen periódico de memoria** por el propio LLM (1 ciclo auto/día)
3. **Sandbox de skills** con subprocess aislado + timeout + whitelist de imports
4. **Confirmación para comandos de escritura** (`rm`, `mv`, `apt install`) vía Telegram inline buttons
5. **Webhooks de Telegram** detrás de VPN (WireGuard) en vez de polling
6. **Métricas**: exportar usage a un CSV/graphite simple para graficar consumo
7. **Multi-model fallback**: si Gemini falla, probar otro proveedor (necesita abstracción de cliente LLM)

### Qué NO intentar en este hardware (por experiencia)
- Modelos LLM locales (ni 1B params entran cómodos en 2GB RAM sin swap-muerte)
- Docker/Kubernetes (ya probado: n8n + opencode fracasaron)
- Bases de datos SQL embebidas grandes (SQLite chico OK, PostgreSQL no)
- Compilar cosas grandes (GCC tardaría horas en RAM limitada)
- Múltiples servicios simultáneos: mantener SOLO bot.service

---

## PARTE 5: COMANDOS DE OPERACIÓN DIARIA

```bash
# Terminal (como jutex):
bot                          # chat interactivo
bot "consulta puntual"
bot --status                 # presupuesto + breaker
bot "/skills"                # listar skills (sin gastar API)
bot "/skill run disk_free"   # ejecutar skill guardada
bot "/errors"                # ver errores recientes

# Servicio:
systemctl --user status|restart|stop bot
journalctl --user -u bot -f          # logs en vivo

# Telegram (@Jutexcompacbot): mismos comandos con /

# Modo bucle autónomo:
bot "/auto on"               # arranca ciclos cada 30 min (máx 6/día)
bot "/stopauto"              # freno de emergencia
bot "/resetauto"             # resetear circuit breaker

# Como root (solo mantenimiento):
su - jutex                   # cambiar a jutex para usar bot
loginctl show-user jutex -p Linger   # verificar arranque al boot
```

## PARTE 6: ARCHIVOS DE REFERENCIA
- `G:\jutex@compacserver\bot.py` — código maestra (subir con scp tras cambios + `systemctl --user restart bot`)
- `G:\jutex@compacserver\Readme.txt` — uso rápido + estado final
- `~/HISTORIA.txt` en la notebook — versión compacta de esta historia

## PARTE 7: EPÍLOGO — v7 "MicroBot" (2026-08-22)

La evolución final del proyecto consolidó todo lo aprendido:

- **Renombre a MicroBot**: servicio `microbot.service` (root, `/opt/microbot/`), comando global `microbot`, memoria en `data/microbot.db`. Fin de la era de servicios de usuario: la caja es suya y corre como root con guarda anti-destructivos.
- **Migración de LLM a OpenRouter Free**: el cerebro ahora usa el endpoint gratuito de OpenRouter (`openrouter/free`, router automático de modelos gratis) con reintentos ante modelos que devuelven vacío. Costo real del proyecto: $0.
- **Multi-respuesta**: además de la respuesta principal, genera hasta 2 variantes útiles por turno.
- **Memoria unificada**: JSON v5 + SQLite v6 migrados a un único SQLite v7 sin pérdidas.
- **Código profesionalizado**: credenciales fuera del código (`config.json` + override `MICROBOT_*`), instalador reproducible, repo público separado del workspace privado.
