# 🤖 MicroBot (v8.1 Universal)
> **Autonomous Edge AI Agent & SysAdmin in a single Python file (~35MB RAM).**  
> *Zero-Bloat. Multiplatform. ReAct Cognitive Engine + SQLite FTS5 Brain + Aider-Style Patching.*  
> 🇪🇸 [Leer en Español](README.es.md)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![RAM Footprint](https://img.shields.io/badge/RAM_Idle-~35MB-brightgreen.svg)]()
[![Cost](https://img.shields.io/badge/Cost-%240%2Fmonth-success.svg)]()
[![Hardware](https://img.shields.io/badge/Tested_on-Pentium_Dual_2008-orange.svg)]()
[![Tests](https://img.shields.io/badge/Tests-24%2F24_Passing-brightgreen.svg)]()

MicroBot proves that you don't need heavy 500MB frameworks, Docker containers, or high-end servers to run a truly autonomous agent. Running seamlessly on a **2008 Intel Pentium Dual T3200 with 2GB RAM**, MicroBot turns any old laptop, Raspberry Pi, or VPS into a self-healing Linux/Windows/macOS sysadmin and personal assistant.

---

### 🥊 Comparison: MicroBot vs Heavy Frameworks

| Feature | **MicroBot** | **LangGraph / CrewAI / AutoGen** |
| :--- | :---: | :---: |
| **RAM Footprint** | **~35 MB** | 400 MB - 2 GB+ |
| **Dependencies** | **1 (`requests`)** | 40+ packages + Docker |
| **Codebase Size** | **1 single file (~750 LOC)** | Thousands of abstraction layers |
| **Minimum Hardware**| **Pentium 2008 / 1GB RAM** | Modern multi-core CPU / 8GB+ RAM |
| **Memory Engine** | **SQLite FTS5 (Semantic, Zero-Token Bloat)** | ChromaDB / Heavy Vector DBs |
| **Patching Style** | **Aider-style Search/Replace Diff** | Full-file destructive rewrites |
| **Monthly Cost** | **$0.00 / month (OpenRouter Free / Gemini)** | High API token burn |

---

### ✨ Core Innovations

- 🧠 **Dual-Role ReAct Engine (CrewAI & DeepSeek Style):**  
  Thinks in two perspectives before acting: `[ARCHITECT]` designs the solution, and `[AUDITOR]` validates RAM safety and command safety.
- ⚡ **Platform Abstraction Layer (PAL):**  
  Zero-dependency telemetry. Direct `/proc` inspection on Linux, native `ctypes` on Windows (no `psutil` compilation needed).
- 🔍 **SQLite FTS5 Semantic Memory:**  
  Injects only the top 3-4 relevant facts/playbooks into context. Saves ~90% of token costs.
- 🛠️ **Aider-Style Surgical Patching:**  
  Applies `<<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE` diffs directly with automatic `ast.parse` syntax verification.
- 🗺️ **AST Repo-Map & Slicer (OpenHands Style):**  
  Extracts structural outlines and line-numbered slices from Python codebases without wasting context tokens.
- 🌐 **Truncated Web Search:**  
  Lightweight DuckDuckGo search capped at 600 chars to eliminate token explosion.
- 📨 **Visible Telegram Pipeline & Outbox:**  
  Real-time editing status bubbles (`Received` ➔ `Thinking` ➔ `Shell` ➔ `Result`) with automatic offline outbox retries.
- ⏰ **24/7 Timekeeper & Nocturnal Vacuum:**  
  Autonomous scheduler for daily routines and a 04:00 AM memory deduplication and WAL truncation routine.

---

### 🚀 Quickstart

1. **Clone & Install:**
   ```bash
   git clone https://github.com/soyjutex/MicroBot.git
   cd MicroBot
   pip install requests
   ```
2. **Configure:**
   ```bash
   cp config.example.json config.json
   # Edit with your Telegram Token and Gemini / OpenRouter API Key
   ```
3. **Run:**
   ```bash
   # Interactive CLI:
   python3 bot.py

   # Telegram Daemon:
   python3 bot.py --daemon

   # Run offline test harness (24 checks):
   python3 tests/test_harness.py
   ```

📜 **License**  
MIT License © 2026 soyjutex
