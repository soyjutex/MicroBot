# BITÁCORA DE EVOLUCIÓN: MicroBot (2026-08-22)

## Resumen de Evolución: De Script a Agente Cognitivo

El proyecto ha pasado por 6 fases críticas para lograr estabilidad y autonomía en hardware limitado (Notebook Pentium Dual 2GB RAM).

### 1. Núcleo v1-v3: Estructura Básica
- Implementación de memoria JSON persistente (`.bot_memory.json`).
- Límites estrictos de consumo (API calls / auto-ciclos).
- Bloqueo de seguridad (Regex para evitar comandos destructivos).
- Uso de `systemd --user` con `linger` para persistencia.

### 2. v4-v5: Inteligencia, Misiones y Autocorrección
- Introducción de "Misiones" (bucle cerrado Pensar-Actuar-Observar).
- Telemetría de hardware (load, ram, temp) inyectada al LLM para prevenir saturación.
- Implementación de `Circuit Breaker` para detectar bucles de error.

### 3. v6.x: Estabilidad Extrema (El "Blindaje")
- **Eliminación de la recursividad peligrosa:** Se eliminó la lógica de "misiones de múltiples pasos" (que causaba `AttributeError`) a favor de una arquitectura de **Planificación Atómica** (todo en un solo turno).
- **Manejo de Errores Defensivo:** Todo el procesamiento JSON ahora incluye validación de tipo `NoneType` para evitar cuelgues del proceso.
- **Multihilo Asíncrono:** Uso de `ThreadPoolExecutor` para separar el polling de Telegram del procesamiento pesado del LLM.
- **Resiliencia de Sistema:** 
    - `fcntl` para locking robusto de procesos (no más PID ghosts).
    - Watchdog en `crontab` (cada 15min) que reinicia el servicio si el bot deja de responder.
    - Logging profesional (`logging` module) para diagnóstico instantáneo.

## Filosofía de Diseño Alcanzada
- **Minimalismo:** Menos líneas de código = menos puntos de fallo.
- **Atomicidad:** Si una tarea falla, el turno termina y se registra el error, pero el bot no entra en bucle.
- **Cognición JSON:** El bot razona en JSON puro para evitar malentendidos de formato.

---
*MicroBot v7.0.0 es ahora un agente que piensa, actúa y aprende sin colgarse.*
