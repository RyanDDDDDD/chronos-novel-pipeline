[中文](README.zh-CN.md) | **English**

# Chronos

**A local-first, multi-agent long-form narrative engine.** It applies software-engineering determinism (author loop, memory state, checkpoint resumption, declarative context) to discipline LLM non-determinism in long-horizon generation.

Current version: **Author Loop Engine era** (author_loop dialogue_mode · setup_chat collaborative worldbuilding · engine–plugin IoC)

---

## Origin & Vision

Chronos draws on three sources of inspiration:

- **[Dify](https://dify.ai/)**'s workflow orchestration — breaking complex tasks into composable, observable multi-step nodes;
- **SillyTavern**'s pluggable customization philosophy — freely assemble/replace/reorder pipeline nodes instead of binding to a fixed template; its World Info/Lorebook-style "retrieve-and-inject setting on demand" also inspired the cross-chapter foreshadowing memory design;
- **AutoNovel** (NousResearch)'s approach to long-horizon quality control — mechanical anti-slop interception and whole-narrative-unit batch generation, both evaluated and partially adopted into the existing anti-AI-tone mechanism and author-granularity experiments.

Long-form chapter writing needs **cross-paragraph entity state**, **human-in-the-loop topic selection**, and resumable checkpoints — so we built a dedicated orchestration kernel from scratch.

The long-term goal is a **fully customizable creative workstation**:

- **The engine only speaks contracts**: the scheduling layer wires up via `AgentHook` and manifest metadata;
- **Agents are plugins**: `hooks/packages/<name>/` (prompt + hook + assets);
- **Orchestration is archivable**: multiple pipeline profiles can be switched, with skill activation configured via the WebUI's "Pipeline Config" view;
- **Human-in-the-loop is built in**: Setup Chat pauses per task to consult the user during collaborative worldbuilding; the author loop's beat-by-beat writing cycle accepts detail feedback and review at each step.

---

## What Problem It Solves

Long-form text can't be written with "one prompt, done." Chronos collapses chapter production into a **beat-by-beat author writing loop**: Setup Chat conversationally pre-builds the outline/beats → a LangGraph whole-chapter graph writes beat by beat → state derivation rolls forward → checkpoint resumption. Creators can step in at any interaction point across both worldbuilding and writing, balancing automation with human intervention.

---

## Core Mechanics

### Author Writing Loop

1. **Collaborative Worldbuilding**: Setup Chat conversationally builds world/cast/plot, and pre-builds the outline into a beat-segmented skeleton.
2. **Whole-Chapter Graph**: under `dialogue_mode`, a LangGraph executes beat by beat (`task_packet` → `author_prose` → `review_stage` → `advance`) — each beat is drafted, then gated by `review_stage` (a fidelity/word-count/style check with up to 2 retries back to `author_prose`; state derivation and cross-chapter archiving happen once the beat passes or exhausts retries). The old "decision LLM picks a skill → user picks an option" per-segment paradigm has been retired.
3. **Consistency**: archive state guards + a rolling tail window of prior prose; memory beyond a couple of beats collapses into a summary as distance grows, without affecting the checkpoint.
4. **Output**: `Chapter_N_author.md`.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) and [protocol-contract.md](docs/protocol-contract.md) for details (Chinese).

### Engine ⇄ Plugin (IoC)

The scheduling core calls each skill's extension points through the `AgentHook` contract; adding a new skill only requires implementing the hook and wiring it into the Pipeline config — zero changes to the engine.

### Context Supply

`ContextRegistry` concurrently assembles data such as address pools and voice profiles per `ContextRequest`; the author loop calls it directly. The old four-stage AgentHook context declaration chain has been retired.

---

## Architecture at a Glance

```text
┌─────────────────────────────────────────────────────────────┐
│  WebUI (React 19 + Vite · React Query · React Router · RTK)  │
│         Author chat stream · Setup Chat · Pipeline Config     │
│              (Desktop shell: Tauri, see "Getting Started")    │
└──────────────────────────┬──────────────────────────────────┘
                           │  REST + WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│  api/          hub.py (MessageHub) · routes.py · services/   │
├─────────────────────────────────────────────────────────────┤
│  engine/author_loop/dialogue_mode/   LangGraph whole-chapter  │
│    graph: task_packet → author_prose → review_stage → advance │
│  engine/setup_chat/   Collaborative worldbuilding (chat-driven)│
│  engine/setup/        world · cast · plot batch build (legacy)│
│  engine/execution/    AgentHook contract                      │
├─────────────────────────────────────────────────────────────┤
│  context/      ContextRegistry (zero-RPC data supply)         │
│  hooks/packages/   Agent plugins                              │
└─────────────────────────────────────────────────────────────┘
```

> **History**: the V8–V11 LangGraph DAG segment-tagging pipeline, and the later "decision picks a skill → build_options produces a plan" per-segment paradigm, have both been retired; the manifest now only serves as agent-meta and skill-wiring metadata — it does not drive runtime topology.

---

## Quick Start

```powershell
uv sync
copy config\config.example.json config\config.json
uv run python run.py --dev    # single terminal, both processes (engine+gateway) + Vite
# or: npm install && npm run dev   (single process, equivalent to run.py --sequenced --no-browser)
# Desktop shell dev: npm run tauri:dev; packaged build: npm run tauri:build
```

See [GETTING_STARTED.md](GETTING_STARTED.md) for details.

---

## Documentation

| Doc | Content |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture overview (Chinese) |
| [docs/AGENT_PACKAGE.md](docs/AGENT_PACKAGE.md) | Agent package spec (Chinese) |
| [docs/TECHNICAL_JOURNEY.md](docs/TECHNICAL_JOURNEY.md) | Engineering journey write-up (Chinese) |
| [docs/README.md](docs/README.md) | Documentation index (Chinese) |

---

*Chronos | Author Loop Engine | Industrial-grade long-form fiction generation*
