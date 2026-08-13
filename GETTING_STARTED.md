[中文](GETTING_STARTED.zh-CN.md) | **English**

# Chronos Engine — Getting Started

Chronos is a multi-agent orchestration engine built from scratch for **long-form chapter writing**, inspired by **Dify-style workflow orchestration**; the target experience is close to **SillyTavern's pluggable customization** — freely assemble, replace, and reorder pipeline nodes instead of binding to a fixed template. See [README.md](README.md#origin--vision) for background.

---

## Requirements

| Item | Requirement |
|------|------|
| Python | 3.12+ (managed via `uv`) |
| Package manager | `uv` (replaces pip/venv) |
| Node.js | 18+ and `npm` (frontend & desktop shell dependency) |
| Local models | LM Studio / Ollama, OpenAI-compatible endpoint recommended |
| Cloud models | Anthropic / OpenAI / DeepSeek API key (optional) |

Install dependencies:

```powershell
uv sync
```

---

## Configuration

All settings are managed through `config/config.json`. First-time setup:

```powershell
copy config\config.example.json config\config.json
```

### Core `config.json` fields

```json
{
  "llm": {
    "cloud_model_id": "claude-opus-4-7",   // cloud text model id (config/model_catalog.json presets, or a custom entry in custom_models)
    "custom_models": [],                   // user-defined models (both text and image-gen live here), see "API / Model Configuration" below
    "local_base_url": "http://localhost:1234/v1",  // local LLM endpoint (LM Studio / Ollama)
    "local_model": "local-model"
  },
  "api": {
    "model_api_keys": {},        // API keys keyed by model id, e.g. {"claude-opus-4-7": "sk-..."}
    "search_provider": "tavily", // web search provider: tavily | baidu_qianfan
    "tavily_api_key": "",
    "qianfan_api_key": ""
  },
  "server": {
    "engine_port": 8776          // internal engine port
  }
}
```

> See `config/config.example.json` for the full set of default fields; the effective value at runtime is a deep merge of the defaults and `config.json` (`src/backend/utils/config.py`).

### API / Model Configuration: Four Independent Capabilities

**Text generation, image recognition (vision), image generation, and web search** are four completely independent configuration paths — each can point to a different model and API key, with no crosstalk:

| Capability | Where to configure | Takes effect |
|------|----------|----------|
| **Text generation** | WebUI "Service Config" page → Models → Text tab: pick a preset cloud model (Claude / DeepSeek / Qwen / Gemini from `config/model_catalog.json`) or add a custom entry (`llm.custom_models`, `provider` = `openai_compatible` / `anthropic`); local models use the "Local" tab (`llm.local_base_url` + `local_model`, LM Studio / Ollama, no key needed). API keys are stored per model id in `api.model_api_keys` | Immediately, on save (resets the cloud LLM cache + rebuilds the setup-chat agent) — no restart needed |
| **Image recognition (vision)** | Not a separate provider — pick any already-configured text model (cloud preset or custom) that supports vision, then bind it as `model_ref` on the "Image Recognition" / "One-click Setup Build" / "Text Recognition" capability nodes in the WebUI's "Pipeline Config" view (configured per novel, stored in that novel's `author_loop_skill_prefs.json`) | On the next call after saving |
| **Image generation** | WebUI "Service Config" page → Models → Image tab: add a custom entry (`llm.custom_models` with `provider: "image_gen"`, backed by Novita, whose checkpoint model list is fetched live), then bind it as `model_ref` on the "Portrait Generation" node in the "Pipeline Config" view | Saving the key triggers a Novita model-list refresh; binding takes effect on the next generation |
| **Web search** | WebUI "Service Config" page → "API Keys" section: pick one `search_provider` (Tavily or Baidu Qianfan) and fill in its key (`api.tavily_api_key` / `api.qianfan_api_key`); `search_top_k` caps results per query | Immediately, on save |

> **Don't confuse this with RAG**: the embedding model used for retrieval-augmented memory (`BAAI/bge-small-zh-v1.5`) is a fixed local ONNX model (`src/backend/rag/embedding.py`, run via FastEmbed) — completely unrelated to the "Web search" row above. It needs no configuration, no key, and isn't affected by `search_provider`.

---

## Quick Start

The root `run.py` is the unified entry point; by default it starts the WebUI server.

```powershell
# Dev mode — single terminal, Ctrl+C stops both backend and Vite (recommended: engine+gateway dual process)
uv run python run.py --dev

# Or via root npm (run npm install first), single-process sequential start (equivalent to run.py --sequenced --no-browser)
npm run dev

# Production mode (backend only, visit http://localhost:8775 manually)
uv run python run.py

# CLI debug mode (skip auto-opening the browser)
uv run python run.py --no-browser
```

> **Do not** run `npm run dev` inside `src/frontend` in a separate terminal while starting the backend in another: Ctrl+C in the frontend terminal only stops Vite, and the backend on `:8775` keeps running. Use one of the two "single entry point" methods above instead.

Once started, pick a chapter in the browser and click "Start Author Loop" to begin the writing cycle.

---

## Author Writing Flow Overview (Dialogue Mode)

The system currently uses a **dialogue-driven author loop** (`dialogue_mode`); the old per-segment option-picking mode and the segment-level DAG tagging pipeline have both been retired.

| Stage | Description |
|------|------|
| **1. Collaborative Worldbuilding (Setup Chat)** | The Setup Chat agent interactively builds world / cast / plot, pre-building the outline into a beat-segmented skeleton with dialogue design |
| **2. Whole-Chapter Graph Writing (Dialogue Mode)** | A LangGraph whole-chapter graph executes beat by beat: `task_packet` (assemble context) → `author_prose` (draft prose) → `derive_states` (state derivation & snapshot update) → `advance` (move to next beat) |
| **3. Consistency & Checkpointing** | Archive state guards + a dynamic tail window of prior prose; memory beyond a couple of beats collapses into a summary as distance grows; checkpoints auto-save for resumable writing |
| **4. Output** | Chapters are auto-saved as `chapters/chapter_XXX/Chapter_N_author.md` |

- **Skill & node config**: configure multiple profiles (`manifest.json` / `author_loop_skill_prefs.json`) and capability-node LLM parameters (one-click setup build `auto_build_setup`, image recognition, identity generation, etc.) in the WebUI's "Pipeline Config" view.
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the detailed architecture contract (Chinese).

---

## Maintenance & Ops Tools

The `scripts/` directory provides a set of production-grade ops and analysis tools:

- **Prompt parsing/debugging**: `uv run python scripts/prompt_parse.py -c <chapter>` (parses each LLM's system/user prompt and reply from the streaming log)
- **State self-heal & reset**: `uv run scripts/reset_pipeline_state.py` (clears dirty runtime state; add `--chapter N` to reset a specific chapter's artifacts)
- **Token & cost analysis**: `uv run python scripts/token_report.py --chapter <chapter>` (aggregates token consumption & cost estimate by step/agent)
- **Tool-call diagnostics**: `uv run python scripts/tool_report.py --chapter <chapter>` (analyzes tool-call success rate and results)
- **Log export to Markdown**: `uv run python scripts/log_export.py --chapter <chapter>` (converts NDJSON logs into structured Markdown)
- **Agent package validation**: `uv run python scripts/validate_agent_packages.py` (checks Agent Package ↔ manifest wiring consistency)
- **AI-tone analysis**: `uv run python scripts/ai_word_report.py` (measures density of common AI-generated words/phrasing in output)

See 📖 [Ops & Analysis Scripts Guide (scripts/README.md)](./scripts/README.md) for more (Chinese).

---

## Tauri Desktop Packaging (shipping installers to end users)

To ship a build to users without a Python/Node environment, package it as a native desktop installer with Tauri:

```powershell
# Desktop shell dev
npm run tauri:dev

# Build a distributable installer
npm run tauri:build
```

Internally this runs, in order (chained by `scripts/release/build_tauri_sidecar.ps1`):

1. `build_frontend_dist.ps1` — `npm install` + `npm run build`, producing `src/frontend/dist`
2. `build_backend_exe.ps1` — `uv sync --extra release` installs PyInstaller, builds `dist/chronos/` per `release/windows/chronos-win-portable.spec` (bundling hooks/skills/frontend_dist), copies `chronos.exe` into `src-tauri/binaries/`, and `_internal/` into `src-tauri/resources/`
3. The Tauri bundler compiles the sidecar + resources + native shell into an installer

Build artifacts land in `src-tauri/target/release/bundle/` (an NSIS `.exe` installer by default on Windows). After installation, users launch the native window and the backend runs as a sidecar, starting and stopping with the window automatically.

---

## Automated Tests

```powershell
# Backend pytest suite
uv run pytest tests/ -v

# Engine core tests only
uv run pytest tests/engine/ -v

# Frontend build & tests (from src/frontend)
npm --prefix src/frontend run test     # vitest unit tests
npm --prefix src/frontend run lint     # eslint
npm --prefix src/frontend run build    # TypeScript type-check + Vite build
```
