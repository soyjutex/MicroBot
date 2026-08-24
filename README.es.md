# 🤖 MicroBot (v8.1 Universal)
> **Agente autónomo de IA y SysAdmin en un solo archivo de Python (~35MB RAM).**  
> *Cero bloat. Multiplataforma. Motor cognitivo ReAct + Memoria SQLite FTS5 + Parches estilo Aider.*  
> 🇬🇧 [Read in English](README.md)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![RAM Idle](https://img.shields.io/badge/RAM_Idle-~35MB-brightgreen.svg)]()
[![Costos](https://img.shields.io/badge/Costos-%240%2Fmes-success.svg)]()
[![Hardware](https://img.shields.io/badge/Testeado_en-Pentium_Dual_2008-orange.svg)]()
[![Tests](https://img.shields.io/badge/Tests-24%2F24_Aprobados-brightgreen.svg)]()

MicroBot demuestra que no necesitas frameworks pesados de 500MB, contenedores Docker ni servidores costosos para correr un agente verdaderamente autónomo. Diseñado y probado en una **Intel Pentium Dual T3200 de 2008 con 2GB de RAM**, MicroBot convierte cualquier vieja laptop, Raspberry Pi o VPS en un sysadmin y asistente personal autónomo.

---

### 🥊 Comparación: MicroBot vs Frameworks Pesados

| Característica | **MicroBot** | **LangGraph / CrewAI / AutoGen** |
| :--- | :---: | :---: |
| **Consumo de RAM** | **~35 MB** | 400 MB - 2 GB+ |
| **Dependencias** | **1 (`requests`)** | 40+ paquetes + Docker |
| **Tamaño de Código** | **1 archivo único (~750 LOC)** | Miles de capas de abstracción |
| **Hardware Mínimo** | **Pentium 2008 / 1GB RAM** | CPU multi-core / 8GB+ RAM |
| **Motor de Memoria** | **SQLite FTS5 (Semántica, Cero Bloat)** | ChromaDB / Vector DBs pesadas |
| **Estilo de Edición** | **Parches Search/Replace tipo Aider** | Reescrituras destructivas completas |
| **Costo Mensual** | **$0.00 / mes (OpenRouter Free / Gemini)** | Alto consumo de tokens |

---

### ✨ Innovaciones Principales

- 🧠 **Motor ReAct Dual-Role (Estilo CrewAI & DeepSeek):**  
  Piensa en dos perspectivas antes de actuar: `[ARQUITECTO]` diseña la solución y `[AUDITOR]` valida seguridad y consumo de RAM.
- ⚡ **Capa de Abstracción de Plataforma (PAL):**  
  Telemetría sin dependencias. Inspección directa de `/proc` en Linux y `ctypes` nativo en Windows.
- 🔍 **Memoria Semántica SQLite FTS5:**  
  Inyecta solo los 3-4 hechos/recetas relevantes al contexto, ahorrando hasta un 90% en tokens.
- 🛠️ **Parches Quirúrgicos estilo Aider:**  
  Aplica bloques `<<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE` directamente con verificación automática de sintaxis `ast.parse`.
- 🗺️ **AST Repo-Map & Slicer (Estilo OpenHands):**  
  Extrae esquemas estructurales y fragmentos numerados de código Python sin gastar tokens de contexto.
- 🌐 **Búsqueda Web Truncada:**  
  DuckDuckGo Lite limitado a 600 caracteres para eliminar explosiones de tokens.
- 📨 **Pipeline Visible en Telegram & Outbox:**  
  Burbujas de estado en tiempo real (`Recibido` ➔ `Pensando` ➔ `Shell` ➔ `Resultado`) con reintentos offline automáticos.
- ⏰ **Timekeeper 24/7 y Vacuum Nocturno:**  
  Scheduler autónomo y rutina nocturna de deduplicación a las 04:00 AM.

---

### 🚀 Inicio Rápido

1. **Clonar e instalar:**
   ```bash
   git clone https://github.com/soyjutex/MicroBot.git
   cd MicroBot
   pip install requests
   ```
2. **Configurar:**
   ```bash
   cp config.example.json config.json
   # Edita con tu Token de Telegram y tu API Key de Gemini / OpenRouter
   ```
3. **Ejecutar:**
   ```bash
   # CLI interactiva:
   python3 bot.py

   # Daemon de Telegram:
   python3 bot.py --daemon

   # Correr pruebas offline (24 validaciones):
   python3 tests/test_harness.py
   ```

📜 **Licencia**  
Licencia MIT © 2026 soyjutex
