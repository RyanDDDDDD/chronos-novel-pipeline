"""Project path constants — single source of truth for all file paths."""
import contextlib
import contextvars
import json
import os
import sqlite3
import sys

_DEV_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


def _writable_root() -> str:
    """User-writable state root (config/data/pipelines/logs/var).

    Priority: CHRONOS_ROOT env (set by the Tauri shell to the app's local data dir when
    spawning the sidecar; see src-tauri/src/lib.rs) > frozen exe's own directory
    (double-click fallback without a launcher) > dev repo root. PyInstaller's _MEIPASS
    holds read-only bundled assets and must never be used for state that needs to
    persist across runs.
    """
    env = os.environ.get("CHRONOS_ROOT")
    if env:
        return os.path.abspath(env)
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return _DEV_ROOT


def _bundle_root() -> str:
    """Read-only shipped-asset root (hooks/ skills/); PyInstaller onedir embeds these under _MEIPASS."""
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return str(meipass)
    return _DEV_ROOT


PROJECT_ROOT = _writable_root()
_BUNDLE_ROOT = _bundle_root()

#──Configuration ───────────────────────────────────────────────────────────────
CONFIG_DIR          = os.path.join(PROJECT_ROOT, "config")
CONFIG_PATH         = os.path.join(CONFIG_DIR, "config.json")
CONFIG_EXAMPLE_PATH = os.path.join(CONFIG_DIR, "config.example.json")
MODEL_CATALOG_PATH  = os.path.join(CONFIG_DIR, "model_catalog.json")

#── Pipeline file (multiple pipelines can be switched)───────────────────────────────────────
#Each archive: manifest.json + author_loop_skill_prefs.json (optional sidecar);
#Save config/pipelines/<id>/; active.json to remember who is currently selected. Whole directory gitignore.
_DEFAULT_PIPELINE_ID = "default"


def pipelines_dir() -> str:
    """The root directory of all pipeline files; CHRONOS_PIPELINES_DIR can be overridden (for testing)."""
    return os.environ.get("CHRONOS_PIPELINES_DIR") or os.path.join(CONFIG_DIR, "pipelines")


def active_pointer_path() -> str:
    return os.path.join(pipelines_dir(), "active.json")


def active_pipeline_id() -> str:
    """
Read the active field of active.json; if it is missing/damaged, fallback to default (not thrown)."""
    try:
        with open(active_pointer_path(), encoding="utf-8") as f:
            aid = json.load(f).get("active")
        if isinstance(aid, str) and aid:
            return aid
    except (OSError, json.JSONDecodeError):
        pass
    return _DEFAULT_PIPELINE_ID


def active_pipeline_dir() -> str:
    return os.path.join(pipelines_dir(), active_pipeline_id())


def manifest_path() -> str:
    """The manifest of the current pipeline; CHRONOS_MANIFEST can be overridden (scripts/tests convention)."""
    return os.environ.get("CHRONOS_MANIFEST") or os.path.join(active_pipeline_dir(), "manifest.json")

#── Data ───────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(PROJECT_ROOT, "data")


#──Novel file (multiple novels can be switched; the content axis is orthogonal to the pipeline file)──────────────────────────
#Each novel data/novels/<id>/{lore,plot,chapters}; active.json records who is currently selected. Whole directory gitignore.
#Data paths are functions (non-consts) to support runtime switching - constants are bound once at import time and cannot be switched.
_DEFAULT_NOVEL_ID = "default"


def novels_dir() -> str:
    """
All novel file root directories; CHRONOS_NOVELS_DIR can be covered (for testing)."""
    return os.environ.get("CHRONOS_NOVELS_DIR") or os.path.join(DATA_DIR, "novels")


def novels_trash_dir() -> str:
    """Deleted novel recycle bin; the entire directory is moved here, and scanning and slugify are not involved."""
    return os.path.join(novels_dir(), ".trash")


def active_novel_pointer_path() -> str:
    """Legacy active.json location -- no longer read at runtime (active novel now lives in
    the _registry.sqlite3 `novels.is_active` column, see repositories/registry_store.py).
    Kept only for scripts/migrate_json_to_sqlite.py to read the old pointer once when
    backfilling the registry."""
    return os.path.join(novels_dir(), "active.json")


_novel_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "active_novel_override", default=None
)


def _active_novel_id() -> str:
    """CHRONOS_ACTIVE_NOVEL overrides > registry.is_active row > default (does not throw)."""
    env = os.environ.get("CHRONOS_ACTIVE_NOVEL")
    if env:
        return env
    try:
        from repositories.registry_store import get_registry_connection

        row = get_registry_connection().execute(
            "SELECT id FROM novels WHERE is_active = 1 LIMIT 1"
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    except sqlite3.Error:
        pass
    return _DEFAULT_NOVEL_ID


def active_novel_id() -> str:
    """Currently active novel: Background tasks can be pinned within this coroutine using use_novel; otherwise, the global pointer will be rolled back."""
    override = _novel_override.get()
    return override if override is not None else _active_novel_id()


@contextlib.contextmanager
def use_novel(novel_id: str):
    """
Pin the active novel in the context of this coroutine (used for background build to avoid being polluted by concurrent novels)."""
    token = _novel_override.set(novel_id)
    try:
        yield
    finally:
        _novel_override.reset(token)


def active_novel_dir() -> str:
    return os.path.join(novels_dir(), active_novel_id())


def novel_dir(novel_id: str) -> str:
    """Explicit-novel_id variant of active_novel_dir() — used when persisting or migrating a
    specific novel that may not be the currently active one."""
    return os.path.join(novels_dir(), novel_id)


def novel_attachments_dir(novel_id: str | None = None) -> str:
    """Per-novel attachment library root (data/novels/<id>/assets/attachments)."""
    nid = novel_id if novel_id is not None else active_novel_id()
    return os.path.join(novels_dir(), nid, "assets", "attachments")


def novel_attachment_upload_temp_dir(novel_id: str | None = None) -> str:
    """Per-novel staging dir for streamed image uploads before subprocess compression."""
    return os.path.join(novel_attachments_dir(novel_id), ".upload_tmp")


def lore_dir() -> str:
    return os.path.join(active_novel_dir(), "lore")


def archive_dir() -> str:
    return os.path.join(lore_dir(), "archives")


def portrait_dir() -> str:
    return os.path.join(active_novel_dir(), "assets", "portraits")


def portrait_path(filename: str) -> str:
    return os.path.join(portrait_dir(), filename)


def plot_library_path() -> str:
    return os.path.join(active_novel_dir(), "plot", "plot_library.json")


def lore_library_path() -> str:
    return os.path.join(lore_dir(), "character_lore_library.json")


def story_character_config_path() -> str:
    return os.path.join(lore_dir(), "story_character_config.json")


def relationship_edges_path() -> str:
    """Append-only edge log (one JSON object per line, `{from, to, nature, relationship_anchor,
    from_ref_terms, to_ref_terms}`) -- generated incrementally as characters are created, folded
    by relationship_graph.py::load_graph() into the current-state view. Never read-modify-written
    as a whole document -- see docs/superpowers/specs/2026-07-20-relationship-graph-incremental-edges-design.md."""
    return os.path.join(lore_dir(), "relationship_edges.jsonl")


def sandbox_event_log_path() -> str:
    """Per-novel append-only event journal shared by story_sandbox and author_loop (see
    engine.memory_recall.event_log) -- entries carry both chapter and turn_index (turn_index is
    a novel-wide monotonic sequence number, not sandbox-turn-specific)."""
    return os.path.join(lore_dir(), "sandbox_event_log.json")


def recall_cooldown_path() -> str:
    """Cross-session recall-injection cooldown ledger (per-novel, small dict {cooldown_key:
    last_seen_turn_index}). Shared by story_sandbox and author_loop -- both write into the same
    event log's turn_index sequence, so the cooldown ledger tracking "don't re-inject within N
    entries" must also be shared, not per-caller."""
    return os.path.join(lore_dir(), "recall_cooldown.json")


def chapters_dir() -> str:
    return os.path.join(active_novel_dir(), "chapters")


def world_dir() -> str:
    return os.path.join(active_novel_dir(), "world")


def world_bible_path() -> str:
    return os.path.join(world_dir(), "world_bible.json")


#── Engine built-in shared library (cross-theme common reference table; globally shared, not per-novel)──────────────────────
def lib_dir() -> str:
    """
The engine's built-in shared library directory; CHRONOS_LIB_DIR can be covered (for testing)."""
    return os.environ.get("CHRONOS_LIB_DIR") or os.path.join(DATA_DIR, "lib")


def prose_styles_dir() -> str:
    """自动生成的 per-novel 文风预设根目录；生成后进全局文风库，跨小说都可选用——与
    skills/prose-styles/ 的静态手写预设区分开，落在 data/ 下（整体已 gitignore，不进版本，
    对齐 config/pipelines 的“live 数据不进版本”约定）。"""
    return os.path.join(DATA_DIR, "prose_styles")


def setup_chat_dir() -> str:
    return os.path.join(active_novel_dir(), "setup_chat")


def setup_chat_checkpoint_path() -> str:
    return os.path.join(setup_chat_dir(), "checkpoint.sqlite")


def construction_plan_path() -> str:
    # Legacy path; JSON-plan orchestration retired — kept for setup_chat dir cleanup.
    return os.path.join(setup_chat_dir(), "construction_plan.json")


def setup_chat_session_dir(novel_id: str | None = None) -> str:
    """Session layer interaction recording directory (per-novel under data/novels/<id>/session)."""
    nid = novel_id if novel_id is not None else active_novel_id()
    return os.path.join(novels_dir(), nid, "session")


def novel_db_path(novel_id: str | None = None) -> str:
    """Per-novel SQLite db path (repositories/sqlite_store.py) -- SSOT so SqliteStore and
    the vector-chunk store (rag/vector_store.py) resolve the identical file."""
    nid = novel_id if novel_id is not None else active_novel_id()
    return os.path.join(novel_dir(nid), "chronos.sqlite3")


def entity_index_cache_dir(novel_id: str) -> str:
    """Explicit-novel_id variant (not active_novel_dir()-derived) -- entity_index persistence
    needs to read/write an arbitrary novel's cache at process-startup recovery time, which may
    not be the currently active novel."""
    return os.path.join(novels_dir(), novel_id, "cache", "entity_index")

#──Runtime plug-in root (Agent Package/File/Context three categories)─────────────────────────
HOOKS_ROOT        = os.environ.get("CHRONOS_HOOKS_ROOT") or os.path.join(_BUNDLE_ROOT, "hooks")
AGENTS_DIR        = os.path.join(HOOKS_ROOT, "packages")
ARCHIVE_HOOKS_DIR = os.path.join(HOOKS_ROOT, "archive")
#Main author's quality self-review plug-in directory (loader is in src, plug-in is in hooks/review/<name>/hook.py)
REVIEW_HOOKS_DIR = os.path.join(HOOKS_ROOT, "review")
CONTEXT_HOOKS_DIR = os.path.join(HOOKS_ROOT, "context")
#角色内容包根目录（gender/physique 封闭集扩展 + 自定义字段声明；可整体删除，引擎回落通用基线）
CONTENT_PACKS_DIR = os.path.join(HOOKS_ROOT, "content_packs")
#Cross-agent protocol Markdown (do not enter hooks/)
SKILLS_DIR        = os.path.join(_BUNDLE_ROOT, "skills")
SETUP_CHAT_SKILLS_DIR = os.path.join(SKILLS_DIR, "setup_chat_skills")
#外部导入 skill（用户资产，gitignore 的 data/ 下；prompt-only——本目录内任何代码永不执行）
IMPORTED_SKILLS_DIR = os.path.join(PROJECT_ROOT, "data", "skills")
SCRIPTS_DIR  = os.path.join(PROJECT_ROOT, "scripts")
VAR_DIR      = os.path.join(PROJECT_ROOT, "var")   #Engine runtime products (non-authored data, gitignore")


def engine_logs_dir() -> str:
    """
PromptLogger NDJSON log directory (engine_server)."""
    return os.path.join(PROJECT_ROOT, "logs", "engine_server")


def alarms_log_path() -> str:
    """Persistence NDJSON of guard/self-audit alarms (appended across runs for statistical alarm frequency to determine retention and deletion)."""
    return os.path.join(engine_logs_dir(), "alarms.ndjson")


def prompt_dump_path(chapter: int) -> str:
    """保存章节时由 prompt_parse 生成的本章最新一轮全量 prompt 可读文本(每次保存覆盖)。"""
    return os.path.join(PROJECT_ROOT, "logs", "parsed", f"chapter_{chapter:03d}_latest.txt")


#── Backend ───────────────────────────────────────────────────────────────
BACKEND_DIR = os.path.join(PROJECT_ROOT, "src", "backend")


#──Chapter Path Assist─────────────────────────────────────────────────────────
def get_chapter_dir(chapter: int) -> str:
    """
Unifiedly generate the 'chapters/Chapter X' directory path (resolved to the active novel)."""
    return os.path.join(chapters_dir(), f"第{chapter}章")


def get_character_archive_dir(chapter: int) -> str:
    """Generate 'chapters/Chapter X/characters' directory path uniformly."""
    return os.path.join(get_chapter_dir(chapter), "characters")


def author_loop_graph_checkpoint_path() -> str:
    """
LangGraph native checkpoint sqlite for the whole chapter map in line mode (per active novel, thread_id=ch{chapter number} distinguishes chapters)."""
    return os.path.join(chapters_dir(), "_author_loop_graph.sqlite")


def story_sandbox_checkpoint_path() -> str:
    """Story-sandbox's own LangGraph checkpoint sqlite (per active novel, thread_id=
    f"{novel_id}:{chapter}" distinguishes chapters). Never shared with setup_chat's or
    author_loop's checkpoint files — a bug in one must not corrupt threads for the other."""
    return os.path.join(chapters_dir(), "_story_sandbox.sqlite")


def story_sandbox_branches_path() -> str:
    """Per-novel story-branch registry: which independent story lines exist under each chapter
    (chapter=0 = free mode). See engine/story_sandbox/branches.py."""
    return os.path.join(chapters_dir(), "_story_sandbox_branches.json")


def author_loop_journal_path(chapter: int) -> str:
    """Main journal path (same directory as checkpoint, per-novel live, gitignore)."""
    return os.path.join(get_chapter_dir(chapter), f"chapter_{chapter:03d}_journal.ndjson")


def skill_prefs_path() -> str:
    """Per-novel dialogue/skill/LLM-sampling-param sidecar (one independent file per novel,
    under active_novel_dir; writable at runtime, gitignore). Was pipeline-profile-scoped and
    shared across novels before 2026-08 -- moved here so per-novel tuning doesn't leak across
    novels that happen to share a profile."""
    return os.path.join(active_novel_dir(), "author_loop_skill_prefs.json")
