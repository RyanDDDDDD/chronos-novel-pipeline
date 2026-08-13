"""dialogue prefs sidecar: round trip + missing/bad file fault tolerance + atomic writes."""
from __future__ import annotations

from domain.model_profile import ThinkingEffort, resolve_thinking_bind
from repositories.sqlite_store import SqliteStore
from utils.paths import active_novel_id

_PREFS_DOC_KEY = "author_loop_skill_prefs"


def _store() -> SqliteStore:
    return SqliteStore(active_novel_id())


def _read_raw() -> dict:
    """Read the entire sidecar; missing/bad → {}."""
    data = _store().get_doc(_PREFS_DOC_KEY, "")
    return data if isinstance(data, dict) else {}


def _atomic_write(doc: dict) -> None:
    _store().save_doc(_PREFS_DOC_KEY, "", doc)


DEFAULT_TARGET_WORDS = 3000
DEFAULT_AUTO_BUILD_CHARACTER_COUNT = 5
DEFAULT_AUTO_BUILD_CHAPTER_COUNT = 3
DEFAULT_RECALL_COOLDOWN_TURNS = 10
DEFAULT_RECALL_TOP_K = 5
_DEAD_TOP_LEVEL_KEYS = frozenset({"self_review", "profile_kind", "expansion"})
_LLM_PARAM_NODE_IDS = frozenset({"director", "review", "state_derive"})
_SANDBOX_LLM_PARAM_NODE_IDS = frozenset({
    "prose", "derive_char", "derive_scene", "summary_fold", "event_extract", "profile_mutate",
    "suggest", "dialogue_draft", "identify_cast", "selection_rewrite",
})
_STYLE_GUARD_LLM_PARAM_NODE_IDS = frozenset({"director"})
_STYLE_GUARD_SANDBOX_LLM_PARAM_NODE_IDS = frozenset({
    "prose", "derive_char", "derive_scene", "summary_fold", "event_extract", "profile_mutate", "suggest",
    "selection_rewrite",
})
_CONCURRENT_DERIVE_CHAR_NODE_IDS = frozenset({"derive_char"})
_FIX_AGENT_NODE_IDS = frozenset({
    "character_fix_agent", "world_fix_agent", "chapter_skeleton_fix_agent",
})
_IMPORT_LLM_PARAM_NODE_IDS = frozenset({
    "text_recognition", "image_recognition", "chat_identity", "review",
    "auto_build_setup", "auto_expand_skeleton", "timeline_derive", "setup_quality_review",
    "skeleton_writer", "beat_dialogue_draft", "prose_style_extraction",
    "incremental_relationship",
}) | _FIX_AGENT_NODE_IDS
_STYLE_GUARD_IMPORT_LLM_PARAM_NODE_IDS: frozenset[str] = frozenset()
_LLM_PARAM_RANGES: dict[str, tuple[float, float]] = {
    "temperature": (0.0, 2.0),
    "top_p": (0.0, 1.0),
    "frequency_penalty": (-2.0, 2.0),
    "presence_penalty": (-2.0, 2.0),
}
_THINKING_EFFORTS = frozenset(e.value for e in ThinkingEffort)
# Core creative nodes default thinking ON; every other pipeline node defaults OFF
# (overrides provider-level default_thinking_enabled, e.g. DeepSeek). The fix agents
# (single-shot, no ReAct loop -- see fix_agent_runner.py) lean on thinking instead of a
# multi-round tool loop to plan every edit in one pass, so they default ON too.
_DEFAULT_THINKING_ENABLED_NODE_IDS = frozenset({
    "director", "prose", "chat_identity",
}) | _FIX_AGENT_NODE_IDS
# Fix agents get a richer default budget than the general MEDIUM fallback below: they only
# run once (no follow-up turn to recover from an under-planned fix), so they're worth the
# extra thinking tokens.
_DEFAULT_THINKING_EFFORT_NODE_IDS: dict[str, ThinkingEffort] = {
    node_id: ThinkingEffort.HIGH for node_id in _FIX_AGENT_NODE_IDS
}


def resolve_llm_param_node_id(agent: str) -> str:
    """Map runtime _log_agent to the llm_params config node id."""
    return agent


def default_enable_thinking_for_node(agent: str) -> bool:
    """Per-node thinking default when enable_thinking is unset in prefs."""
    return resolve_llm_param_node_id(agent) in _DEFAULT_THINKING_ENABLED_NODE_IDS


def default_thinking_effort_for_node(agent: str) -> ThinkingEffort:
    """Per-node thinking-effort default when thinking_effort is unset in prefs."""
    return _DEFAULT_THINKING_EFFORT_NODE_IDS.get(resolve_llm_param_node_id(agent), ThinkingEffort.MEDIUM)


def _clean_llm_params(
    raw: dict, valid_node_ids: frozenset[str], style_guard_node_ids: frozenset[str],
    concurrent_node_ids: frozenset[str],
) -> dict:
    """Whitelist node ids + param names + numeric ranges; bad entries are silently
    dropped rather than raising (same tolerance policy as the rest of this sidecar)."""
    out: dict[str, dict] = {}
    for node_id, params in raw.items():
        if node_id not in valid_node_ids or not isinstance(params, dict):
            continue
        clean: dict[str, float | bool | str] = {}
        for key, (lo, hi) in _LLM_PARAM_RANGES.items():
            if key not in params:
                continue
            value = params[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if lo <= value <= hi:
                clean[key] = float(value)
        if isinstance(params.get("enable_thinking"), bool):
            clean["enable_thinking"] = params["enable_thinking"]
        if params.get("thinking_effort") in _THINKING_EFFORTS:
            clean["thinking_effort"] = params["thinking_effort"]
        model_ref = params.get("model_ref")
        if isinstance(model_ref, str) and model_ref.strip():
            clean["model_ref"] = model_ref.strip()
        if params.get("provider") == "local":
            #Fields persist independently (like enable_thinking/thinking_effort above) so a
            #still-being-edited override (e.g. provider picked, base_url/model not typed yet)
            #round-trips intact instead of vanishing -- completeness is only required for the
            #override to actually take effect, which bind_node_llm's own check enforces.
            clean["provider"] = "local"
            base_url = params.get("base_url")
            if isinstance(base_url, str) and base_url.strip():
                clean["base_url"] = base_url.strip()
            model = params.get("model")
            if isinstance(model, str) and model.strip():
                clean["model"] = model.strip()
        if node_id in style_guard_node_ids and isinstance(params.get("disable_style_guard"), bool):
            clean["disable_style_guard"] = params["disable_style_guard"]
        if node_id in concurrent_node_ids and isinstance(params.get("concurrent"), bool):
            clean["concurrent"] = params["concurrent"]
        if clean:
            out[node_id] = clean
    return out


def resolve_image_recognition_params(import_params: dict) -> dict:
    """Merged params for the single image-import capability node.

    Legacy sidecars may still carry a separate image_batch_consolidator block from
    when cross-page consolidation was exposed as its own pipeline node; image_recognition
    wins on field conflicts."""
    legacy = import_params.get("image_batch_consolidator")
    current = import_params.get("image_recognition")
    legacy_d = legacy if isinstance(legacy, dict) else {}
    current_d = current if isinstance(current, dict) else {}
    return {**legacy_d, **current_d}


def is_image_recognition_configured() -> bool:
    """True when the dialogue import pipeline has a vision model_ref bound."""
    import_params = load_dialogue_prefs().get("import_llm_params", {})
    if not isinstance(import_params, dict):
        return False
    return bool(resolve_image_recognition_params(import_params).get("model_ref"))


def load_dialogue_prefs() -> dict:
    """Line-driven per-agent configuration (target_words,
    disabled_buildtime_review_hooks, disabled_runtime_review_hooks,
    disabled_setup_review_hooks).

    buildtime/runtime/setup review hooks are three independent disable-sets over the
    shared hooks/review/ registry (a hook like "style" can be reused by buildtime/runtime
    but toggled off in only one) -- see chapter_review.py (buildtime, skeleton
    construction), stage_review.py (runtime, author_loop candidate prose), and
    setup_quality_review.py (world/cast gate before persist)."""
    raw = _read_raw().get("dialogue")
    out: dict = {
        "target_words": DEFAULT_TARGET_WORDS,
        "disabled_buildtime_review_hooks": [], "disabled_runtime_review_hooks": [],
        "disabled_setup_review_hooks": [],
        "llm_params": {}, "sandbox_llm_params": {}, "import_llm_params": {},
        "auto_build_character_count": DEFAULT_AUTO_BUILD_CHARACTER_COUNT,
        "auto_build_chapter_count": DEFAULT_AUTO_BUILD_CHAPTER_COUNT,
        "chat_identity": "",
        "recall_cooldown_turns": DEFAULT_RECALL_COOLDOWN_TURNS,
        "recall_top_k": DEFAULT_RECALL_TOP_K,
        "portrait_style_prompt": "", "portrait_negative_prompt": "",
        "portrait_style_preset_id": "anime",
    }
    if isinstance(raw, dict):
        if isinstance(raw.get("target_words"), int) and raw["target_words"] > 0:
            out["target_words"] = raw["target_words"]
        if isinstance(raw.get("auto_build_character_count"), int) and raw["auto_build_character_count"] > 0:
            out["auto_build_character_count"] = raw["auto_build_character_count"]
        if isinstance(raw.get("auto_build_chapter_count"), int) and raw["auto_build_chapter_count"] > 0:
            out["auto_build_chapter_count"] = raw["auto_build_chapter_count"]
        if isinstance(raw.get("recall_cooldown_turns"), int) and raw["recall_cooldown_turns"] > 0:
            out["recall_cooldown_turns"] = raw["recall_cooldown_turns"]
        if isinstance(raw.get("recall_top_k"), int) and raw["recall_top_k"] > 0:
            out["recall_top_k"] = raw["recall_top_k"]
        if isinstance(raw.get("disabled_buildtime_review_hooks"), list):
            out["disabled_buildtime_review_hooks"] = [
                s for s in raw["disabled_buildtime_review_hooks"] if isinstance(s, str)
            ]
        if isinstance(raw.get("disabled_runtime_review_hooks"), list):
            out["disabled_runtime_review_hooks"] = [
                s for s in raw["disabled_runtime_review_hooks"] if isinstance(s, str)
            ]
        if isinstance(raw.get("disabled_setup_review_hooks"), list):
            out["disabled_setup_review_hooks"] = [
                s for s in raw["disabled_setup_review_hooks"] if isinstance(s, str)
            ]
        if isinstance(raw.get("llm_params"), dict):
            out["llm_params"] = _clean_llm_params(
                raw["llm_params"], _LLM_PARAM_NODE_IDS, _STYLE_GUARD_LLM_PARAM_NODE_IDS,
                frozenset(),
            )
        if isinstance(raw.get("sandbox_llm_params"), dict):
            out["sandbox_llm_params"] = _clean_llm_params(
                raw["sandbox_llm_params"], _SANDBOX_LLM_PARAM_NODE_IDS,
                _STYLE_GUARD_SANDBOX_LLM_PARAM_NODE_IDS,
                _CONCURRENT_DERIVE_CHAR_NODE_IDS,
            )
        if isinstance(raw.get("import_llm_params"), dict):
            raw_import = raw["import_llm_params"]
            out["import_llm_params"] = _clean_llm_params(
                raw_import, _IMPORT_LLM_PARAM_NODE_IDS, _STYLE_GUARD_IMPORT_LLM_PARAM_NODE_IDS,
                frozenset(),
            )
            merged_image = resolve_image_recognition_params(raw_import)
            if merged_image:
                cleaned = _clean_llm_params(
                    {"image_recognition": merged_image},
                    _IMPORT_LLM_PARAM_NODE_IDS, _STYLE_GUARD_IMPORT_LLM_PARAM_NODE_IDS,
                    frozenset(),
                ).get("image_recognition")
                if cleaned:
                    out["import_llm_params"]["image_recognition"] = cleaned
        if isinstance(raw.get("chat_identity"), str):
            out["chat_identity"] = raw["chat_identity"].strip()
        if isinstance(raw.get("portrait_style_prompt"), str):
            out["portrait_style_prompt"] = raw["portrait_style_prompt"].strip()
        if isinstance(raw.get("portrait_negative_prompt"), str):
            out["portrait_negative_prompt"] = raw["portrait_negative_prompt"].strip()
        if isinstance(raw.get("portrait_style_preset_id"), str):
            out["portrait_style_preset_id"] = raw["portrait_style_preset_id"].strip() or "anime"
    return out


def save_dialogue_prefs(prefs: dict) -> None:
    """Only the dialogue key is updated; drops legacy dead top-level keys
    (self_review/profile_kind/expansion) opportunistically on every save --
    no separate migration script, the file self-heals the next time it's
    touched (same trade-off as this module's existing missing/bad-file
    tolerance)."""
    doc = {k: v for k, v in _read_raw().items() if k not in _DEAD_TOP_LEVEL_KEYS}
    cur = load_dialogue_prefs()
    if isinstance(prefs.get("target_words"), int) and prefs["target_words"] > 0:
        cur["target_words"] = prefs["target_words"]
    if isinstance(prefs.get("auto_build_character_count"), int) and prefs["auto_build_character_count"] > 0:
        cur["auto_build_character_count"] = prefs["auto_build_character_count"]
    if isinstance(prefs.get("auto_build_chapter_count"), int) and prefs["auto_build_chapter_count"] > 0:
        cur["auto_build_chapter_count"] = prefs["auto_build_chapter_count"]
    if isinstance(prefs.get("recall_cooldown_turns"), int) and prefs["recall_cooldown_turns"] > 0:
        cur["recall_cooldown_turns"] = prefs["recall_cooldown_turns"]
    if isinstance(prefs.get("recall_top_k"), int) and prefs["recall_top_k"] > 0:
        cur["recall_top_k"] = prefs["recall_top_k"]
    if isinstance(prefs.get("disabled_buildtime_review_hooks"), list):
        cur["disabled_buildtime_review_hooks"] = [
            s for s in prefs["disabled_buildtime_review_hooks"] if isinstance(s, str)
        ]
    if isinstance(prefs.get("disabled_runtime_review_hooks"), list):
        cur["disabled_runtime_review_hooks"] = [
            s for s in prefs["disabled_runtime_review_hooks"] if isinstance(s, str)
        ]
    if isinstance(prefs.get("disabled_setup_review_hooks"), list):
        cur["disabled_setup_review_hooks"] = [
            s for s in prefs["disabled_setup_review_hooks"] if isinstance(s, str)
        ]
    if isinstance(prefs.get("llm_params"), dict):
        cur["llm_params"] = _clean_llm_params(
            prefs["llm_params"], _LLM_PARAM_NODE_IDS, _STYLE_GUARD_LLM_PARAM_NODE_IDS,
            frozenset(),
        )
    if isinstance(prefs.get("sandbox_llm_params"), dict):
        cur["sandbox_llm_params"] = _clean_llm_params(
            prefs["sandbox_llm_params"], _SANDBOX_LLM_PARAM_NODE_IDS,
            _STYLE_GUARD_SANDBOX_LLM_PARAM_NODE_IDS,
            _CONCURRENT_DERIVE_CHAR_NODE_IDS,
        )
    if isinstance(prefs.get("import_llm_params"), dict):
        cur["import_llm_params"] = _clean_llm_params(
            prefs["import_llm_params"], _IMPORT_LLM_PARAM_NODE_IDS, _STYLE_GUARD_IMPORT_LLM_PARAM_NODE_IDS,
            frozenset(),
        )
    if isinstance(prefs.get("chat_identity"), str):
        cur["chat_identity"] = prefs["chat_identity"].strip()
    if isinstance(prefs.get("portrait_style_prompt"), str):
        cur["portrait_style_prompt"] = prefs["portrait_style_prompt"].strip()
    if isinstance(prefs.get("portrait_negative_prompt"), str):
        cur["portrait_negative_prompt"] = prefs["portrait_negative_prompt"].strip()
    if isinstance(prefs.get("portrait_style_preset_id"), str):
        cur["portrait_style_preset_id"] = prefs["portrait_style_preset_id"].strip() or "anime"
    doc["dialogue"] = cur
    _atomic_write(doc)


def resolve_node_llm_params(agent: str, llm_params: dict) -> dict:
    """Look up a node's sampling-param overrides by `_log_agent`.
    Unconfigured nodes return {}."""
    params = llm_params.get(resolve_llm_param_node_id(agent))
    return params if isinstance(params, dict) else {}


def resolve_node_base_llm(llm, agent: str, llm_params: dict):
    """Model-swap-only half of bind_node_llm: resolves a configured `model_ref`
    or local-provider override into a concrete chat model, or returns `llm`
    unchanged. Split out from bind_node_llm so callers that still need to call
    `.bind_tools()` (e.g. setup_chat's main agent) can do so on a plain chat
    model before any sampling-param `.bind()` is layered on top -- the
    RunnableBinding that `.bind()` produces does not expose `.bind_tools()`."""
    params = resolve_node_llm_params(agent, llm_params)
    model_ref = params.get("model_ref")
    provider = params.get("provider")
    base_url = params.get("base_url")
    model = params.get("model")
    if model_ref:
        from domain.model_catalog import resolve_model_entry
        entry = resolve_model_entry(model_ref)
        if entry is not None:
            from llm.factory import get_registry_llm
            return get_registry_llm(entry)
    elif provider == "local" and base_url and model:
        from llm.factory import get_node_local_llm
        return get_node_local_llm(base_url, model)
    return llm


def node_llm_sampling_kwargs(base_llm, agent: str, llm_params: dict) -> dict:
    """Sampling-param half of bind_node_llm: everything meant to go through
    `.bind()` (temperature/top_p/... plus the thinking-effort translation).
    Computed against `base_llm` (post model-swap, see resolve_node_base_llm)
    since thinking-kwarg dispatch depends on which concrete client it is."""
    params = dict(resolve_node_llm_params(agent, llm_params))
    enable_thinking = params.pop("enable_thinking", None)
    effort_raw = params.pop("thinking_effort", None)
    params.pop("model_ref", None)
    params.pop("provider", None)
    params.pop("base_url", None)
    params.pop("model", None)
    params.pop("disable_style_guard", None)
    params.pop("concurrent", None)
    effort = (
        ThinkingEffort(effort_raw) if effort_raw in _THINKING_EFFORTS
        else default_thinking_effort_for_node(agent)
    )
    if not isinstance(enable_thinking, bool):
        enable_thinking = default_enable_thinking_for_node(agent)
    thinking_bind = resolve_thinking_bind(
        base_llm,
        enable_thinking=enable_thinking,
        effort=effort,
    )
    if thinking_bind:
        params.update(thinking_bind)
    return params


def bind_node_llm(llm, agent: str, llm_params: dict):
    """Bind a node's configured sampling params onto `llm`, or return it
    unchanged when nothing's configured (avoids a pointless `.bind()` wrapper
    on the hot path for every node that hasn't been tuned)."""
    base_llm = resolve_node_base_llm(llm, agent, llm_params)
    params = node_llm_sampling_kwargs(base_llm, agent, llm_params)
    return base_llm.bind(**params) if params else base_llm
