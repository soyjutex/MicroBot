# PROTOCOLO DE MANTENIMIENTO: compacserver

Este documento registra los procedimientos para gestionar el bot MicroBot en `compacserver` (192.168.x.x).

## 1. Conexión SSH
Se utiliza autenticación por clave pública (Ed25519). 
- **Acceso:** `ssh jutex@192.168.x.x`
- **Configuración:** La clave pública debe estar en `~/.ssh/authorized_keys`. Si se pierde el acceso, debe restaurarse manualmente desde la consola física de la notebook.

## 2. Ejecución y Servicio
El bot corre como un servicio de **systemd de usuario** para persistir reinicios.
- **Servicio:** `~/.config/systemd/user/bot.service`
- **Comandos de gestión:**
  - `systemctl --user status bot`
  - `systemctl --user restart bot`
  - `systemctl --user stop bot`
- **Persistencia al boot:** Se utiliza `loginctl enable-linger jutex` para que el servicio arranque sin necesidad de login.

## 3. Modificación de Archivos (El "Círculo de Confianza")
El bot reside en `~/bot_v6.py`. Para actualizarlo o corregirlo:
1. **Edición:** Modificar localmente en la máquina de desarrollo.
2. **Transferencia:** Usar `scp` para sobreescribir el archivo remoto:
   `scp path/to/local/bot_v6.py jutex@192.168.x.x:/home/jutex/bot_v6.py`
3. **Validación:** Asegurar permisos de ejecución:
   `ssh jutex@192.168.x.x "chmod +x /home/jutex/bot_v6.py"`
4. **Reiniciar:** Aplicar cambios con `systemctl --user restart bot`.

## 4. Estructura del Proyecto (Contexto para IAs)
- **Código:** `~/bot_v6.py` (código maestro).
- **Memoria:** `~/.bot_memory.json` (facts, history, ledger, skills, misiones).
- **Entorno:** Debian 13, Python 3.13, 2GB RAM + zram.
- **Hardware:** Pentium Dual T3200 (sin AVX).
- **Seguridad:** El bot corre como usuario `jutex`. Comandos root restringidos a una whitelist en `/etc/sudoers.d/jutex-bot`.

## 5. Prevención de procesos duplicados (IMPORTANTE)
El bot utiliza un archivo PID en `/tmp/bot.pid` para evitar múltiples instancias. 
- **Regla de oro:** Siempre que modifiques o reinicies el bot, asegúrate de que no haya procesos huérfanos. 
- **Procedimiento de limpieza:** 
  ```bash
  ssh jutex@192.168.x.x "pkill -f bot_v6.py; rm /tmp/bot.pid; systemctl --user restart bot"
  ```
- Nunca asumas que `systemctl restart` limpiará un proceso que se desvinculó de su PID lock. Verifica siempre con `ps aux | grep bot`.

**Nota crítica:** El comando `bot` (usado en shell) es un symlink a `~/bot_v6.py` ubicado en `~/.local/bin/bot`. Si el servicio falla con `203/EXEC`, verificar que el symlink exista y apunte correctamente.
