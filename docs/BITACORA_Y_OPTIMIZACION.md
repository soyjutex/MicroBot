# BITÁCORA DE MANTENIMIENTO Y OPTIMIZACIÓN (MicroBot v6)

Este documento registra nuestra forma de trabajar y las lecciones aprendidas para mantener el bot operativo, escalable y resistente.

## 1. Reglas de Operación Rápida
Para minimizar fallos y maximizar la velocidad de despliegue:

*   **Verificación Previa:** Nunca dar por sentado que el bot corre. Verificar siempre:
    `ssh jutex@192.168.x.x "ps aux | grep bot | grep -v grep"`
*   **Protocolo de Reinicio "Nuclear" (El más rápido):**
    Si algo falla, no intentar "arreglar" el proceso vivo. Matar, limpiar, reiniciar:
    ```bash
    ssh jutex@192.168.x.x "pkill -f bot_v6.py; rm /tmp/bot.pid; systemctl --user restart bot"
    ```
*   **Despliegue sin fricción:**
    Usar siempre `scp` para subir `bot_v6.py` y luego un comando `ssh` concatenado que aplique permisos y reinicie el servicio.
*   **Logs como primera respuesta:**
    Ante cualquier silencio del bot, el comando maestro es:
    `ssh jutex@192.168.x.x "journalctl --user -u bot --no-pager -n 20"`

## 2. Estrategia de Upgrade & Resiliencia
Para que el bot evolucione sin romper el entorno:

*   **Self-Patching:** Seguiremos usando la lógica de `apply_patch()` del bot, pero siempre verificando primero que el código es sintácticamente correcto (`ast.parse`).
*   **Lógica de Reinicio:** El bot tiene un comando `/restart` implementado que sale limpiamente (`sys.exit(0)`). Systemd está configurado con `Restart=always` para que, en cuanto el proceso muere, systemd lo levante inmediatamente (resiliencia automática).
*   **Memoria Segura:** No editar manualmente `~/.bot_memory.json` a menos que sea estrictamente necesario. Usar `/status` para verificar que la memoria no esté corrupta.

## 3. Optimización de Flujo (Instrucción para Agentes Futuros)
Para trabajar rápido y directo:
1. **No ser redundante:** Si ya sabemos que el bot corre en `/home/jutex/bot_v6.py` y es gestionado por `systemd`, saltar directamente a la verificación o al comando de reinicio unificado.
2. **Uso de Alias:** Preferir comandos SSH concatenados que realizan "subir + limpiar + reiniciar" en una sola línea.
3. **Mantenimiento Preventivo:** Si se detecta un proceso bloqueado, matarlo sin dudas. El PID lock es el punto de fallo más común; la limpieza del `/tmp/bot.pid` es obligatoria antes de cualquier `start`.
4. **Comunicación:** Ser extremadamente directo. El usuario prefiere resultados (bot funcionando) sobre explicaciones extensas.

---
*Este proyecto es simple y ágil. Menos es más. Mantener `bot_v6.py` como única fuente de verdad.*
