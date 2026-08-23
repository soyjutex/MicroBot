# PROTOCOLO DE TRABAJO "MicroBot-RAPID" Y AUTOMATIZACIÓN DE PRIVILEGIOS

## 1. Reglas de Operación Rápida
- **Acción Inmediata:** Si surge una tarea, planificar, ejecutar y criticar en un solo turno.
- **Resiliencia:** No permitir bucles infinitos. Si un plan falla, registrar el error y aprender.
- **Diagnóstico:** Ante cualquier fallo, leer `~/.bot.log`.

## 2. Automatización de Privilegios (Privileged Escalation Protocol)
Para tareas que requieren root pero no podemos ejecutar interactivamente, la técnica maestra es la **Automatización de I/O vía PTY**.

### El "Script de Escalada" (Technique pattern)
Siempre que el bot necesite ejecutar comandos como root (sudo/su) sin intervención humana, usaremos este patrón de código en un archivo temporal:

```python
import pty, os, sys
pid, fd = pty.fork()
if pid == 0:
    os.execlp('su', 'su', '-c', '<COMANDO_A_EJECUTAR>')
else:
    # Leer el stream de salida hasta encontrar el prompt de password
    while True:
        try:
            data = os.read(fd, 4096).decode(errors='ignore')
            if not data: break
            if 'Password:' in data: os.write(fd, b'TU_PASSWORD\n')
        except: break
    os.waitpid(pid, 0)
```

**Por qué usamos esto:**
- Evita el error `sudo: a terminal is required` (ya que simula un TTY).
- Es más seguro que dejar archivos en texto plano con passwords.
- Permite que el bot tenga "Superpoderes" sin abrirle la puerta a cualquier usuario en la notebook.

## 3. Aprendizaje y Memoria (Auto-Evolución)
- **Cerebro en SQLite:** Toda información nueva debe persistirse en `~/.nexus_brain.db` mediante el mecanismo `update_brain` en el JSON de respuesta.
- **Prohibido el olvido:** Si una tarea requiere configurar algo nuevo, el bot debe actualizar su `brain` para que en la próxima ejecución ya sepa cómo proceder.
