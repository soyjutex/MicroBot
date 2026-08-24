# MicroBot Architecture

MicroBot is designed around four core architectural pillars, keeping total resource usage under ~35MB RAM while rivaling multi-gigabyte agent frameworks.

```
   ┌─────────────────────────────────────────────────────────────────────────────┐
   │                                                                             │
   │   1. DUAL-ROLE ENGINE (CrewAI/AutoGen)                                      │
   │      Prompt with two brains: [ARCHITECT] designs + [AUDITOR] validates.     │
   │                                                                             │
   │   2. MICRO-GRAPH (LangGraph)                                                │
   │      Deterministic State Machine: PLAN ➔ ACT ➔ OBSERVE ➔ CRITIQUE.          │
   │                                                                             │
   │   3. AST REPO-MAP & SLICER (OpenHands)                                      │
   │      Code navigation without wasting tokens: reads signatures & slices.     │
   │                                                                             │
   │   4. SEARCH & REPLACE ENGINE (Aider)                                        │
   │      Surgical file editing: 30-token diffs without full-file rewrites.      │
   │                                                                             │
   └─────────────────────────────────────────────────────────────────────────────┘
```

## 1. Platform Abstraction Layer (PAL)
The PAL detects the host operating system at startup (`platform.system()`) and abstracts system calls:
- **Linux / macOS**: Direct reading of `/proc/meminfo`, `/proc/loadavg`, and thermal zones. Process group management via `os.setpgid` and `os.killpg`.
- **Windows**: Native `ctypes` calls to `GlobalMemoryStatusEx` and `GetSystemTimes`. Job/process tree termination via `taskkill /T /F`.
- **Instance Locking**: Uses `fcntl.flock` on Unix and `msvcrt.locking` on Windows to guarantee single-instance execution per database.

## 2. SQLite FTS5 Semantic Memory & Playbooks
Instead of heavy vector databases (ChromaDB, FAISS), MicroBot uses SQLite with the built-in `fts5` extension.
- **Fact Storage**: Every turn can extract a declarative fact or a procedural playbook (`[DISPARADOR: ...] -> [SOLUCION: ...]`).
- **Keyword Filtering**: Incoming user queries are stripped of Spanish/English stop words and matched against FTS5 tables, injecting only the top 3-4 relevant snippets into the system prompt.
- **Nocturnal Compaction**: At 04:00 AM, a background daemon deduplicates facts and executes `VACUUM` with `PRAGMA wal_checkpoint(TRUNCATE)` to keep database files lightweight and HDD-friendly.

## 3. ReAct Cognitive Loop & State Machine (`AgentState`)
Migrated from linear execution to a bounded state machine:
- **Step Budget**: Maximum 3 sub-steps per turn (6 for missions) to prevent infinite loops.
- **Loop Guard**: Detects identical command repetitions within the same turn and injects a synthetic observation demanding a strategy change or final conclusion.
- **Auto-Playbook Post-Mortem**: If step $N$ fails and step $N+1$ succeeds, the agent automatically captures the procedural fix without LLM overhead.

## 4. Aider-Style Surgical Patching & OpenHands AST
- **Search & Replace**: Applies standard `<<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE` diffs. Automatically runs `ast.parse()` to guarantee Python syntax validity before writing, creating an automatic timestamped `.bak` backup.
- **AST Slicer**: `get_code_map` builds a structural outline (classes and functions with line numbers) in ~100 tokens, and `read_file_slice` fetches exact line ranges.
