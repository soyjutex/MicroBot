# Guía de operación

> Instalación, actualización y mantenimiento diario. Sin credenciales ni
> detalles de infraestructura privada: solo lo necesario para correr
> MicroBot en tu propia máquina.

---

## Requisitos

- Python 3.9+ (probado en 3.11 y 3.12)
- `pip install requests`
- Un bot de Telegram ([@BotFather](https://t.me/BotFather) → `/newbot`)
- Una API key LLM (OpenRouter tiene modelos free; también sirve Groq,
  Gemini u Ollama local)

## Instalación

```bash
git clone https://github.com/soyjutex/MicroBot.git
cd MicroBot
pip install -r requirements.txt

# configuración mínima
cp config.example.json config.json
# editar config.json: api_key, telegram_token, chat_id

# prueba sin Telegram (CLI interactiva, no gasta el daemon):
python3 bot.py --status        # telemetría + FTS5
python3 bot.py                 # chat por consola
```

### Como servicio (Linux / systemd)

```bash
sudo ./install/install.sh          # instala microbot.service + dashboard
systemctl --user status microbot   # o sudo systemctl status microbot
```

Sin systemd, para pruebas:

```bash
nohup python3 bot.py --daemon > /dev/null 2>&1 &
```

### Windows

```powershell
python bot.py --daemon    # igual que Linux; la PAL detecta el OS
```

Para dejarlo permanente: Programador de tareas → acción
`python.exe G:\ruta\bot.py --daemon`, al inicio de sesión.

---

## Actualización

1. Reemplazar `bot.py` (backup previo si es producción).
2. Validar sintaxis: `python3 -m py_compile bot.py`.
3. Reiniciar el servicio.
4. Verificar en el log: línea `daemon iniciado` + mensaje "online" en Telegram.

La memoria (`data/microbot.db`) nunca se toca entre versiones; las migraciones
usan `setdefault` para agregar claves nuevas sin romper memorias viejas.

## Copia de seguridad

Lo único que hay que guardar:

| Archivo | Qué es |
|---|---|
| `config.json` | credenciales (¡nunca al repo!) |
| `data/microbot.db` | toda la memoria del bot |

La compresión nocturna ya guarda un backup de hechos dentro de la misma DB
(`kv: facts_backup_<fecha>`), pero un dump externo semanal es buena idea:

```bash
cp data/microbot.db backups/microbot_$(date +%F).db
```

## Diagnóstico rápido

| Síntoma | Dónde mirar |
|---|---|
| No responde | log: ¿está vivo el proceso? ¿línea `daemon iniciado`? |
| Recibió pero no contestó | tabla `errors` en la DB; outbox pendiente |
| "Limite diario" | `kv.usage`: presupuesto agotado hasta mañana |
| Dos bots pelean por mensajes | dos daemons con el mismo token: uno solo debe vivir |
| Respuestas lentas | red intermitente; los reintentos + outbox cubren, revisar conectividad |
| RAM baja | el bot se pausa solo (`resources_ok`); cerrar cosas o bajar carga |

## Comandos locales (no gastan API)

```
/status   estado y recursos      /notas    últimas notas guardadas
/nota X   guardar nota           /ideas    ideas guardadas
/idea X   guardar idea           /misiones historial de misiones
/help     ayuda completa         /compactar compresión de memoria manual
/restart  reinicio limpio (el servicio revive)
```
