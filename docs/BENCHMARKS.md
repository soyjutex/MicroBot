# MicroBot Benchmarks

Tested live on a vintage **Intel Pentium Dual T3200 (2.0 GHz, 2 cores released in 2008)** running **Debian 13 (Trixie)** with 2GB of DDR2 RAM.

## 1. Resource Utilization (Idle & Under Load)

| Metric | Idle State | During ReAct Turn (LLM + Shell) |
| :--- | :---: | :---: |
| **RAM Footprint (RSS)** | **34.8 MB** | **38.2 MB** |
| **CPU Usage** | **0.0%** | 2.1% - 5.4% (spike during shell execution) |
| **Disk I/O** | Minimal (WAL mode) | < 1.2 MB written per turn |
| **Database Size** | < 250 KB | Stays < 2 MB (with nocturnal WAL checkpointing) |

## 2. Speed & Latency Benchmarks

- **Offline Test Harness (24 checks):** Completed in **0.18 seconds**.
- **Zero-API Commands (`/disco`, `/top`, `/ip`, `/ping`):** Average response time < **12ms**.
- **Telegram RTT (via `/ping`):** ~750ms.
- **LLM Turn Latency (Gemini Flash Lite / OpenRouter Free):** ~1.8s to 2.4s for a 2-step ReAct diagnostic loop.

## 3. Storage Efficiency (SQLite FTS5 vs Vector DBs)

| Storage Engine | RAM Overhead | Startup Time | Setup Complexity |
| :--- | :---: | :---: | :---: |
| **ChromaDB / Pinecone Client** | ~200 - 450 MB | 3 - 8 seconds | Heavy Python wheels & C++ binaries |
| **MicroBot SQLite FTS5** | **< 2 MB** | **< 15ms** | **Built-in Python stdlib (`sqlite3`)** |
