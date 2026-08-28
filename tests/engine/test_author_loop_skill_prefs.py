"""dialogue prefs sidecar: round trip + missing/bad file fault tolerance + atomic writes."""
import json

import pytest

import engine.modes.author_loop_skill_prefs as sp
from domain.model_profile import ThinkingEffort
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

@pytest.fixture(autouse=True)
def _prefs_sqlite_env(monkeypatch, tmp_path):
    nid = "test-novel"
    (tmp_path / nid).mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", nid)
    from repositories.sqlite_store import close_connection, get_connection
    from utils.paths import novel_dir
    import os
    db_path = os.path.join(novel_dir(nid), "chronos.sqlite3")
    close_connection(db_path)
    conn = get_connection(db_path)
    conn.execute("DELETE FROM documents WHERE doc_key = 'author_loop_skill_prefs'")
    conn.commit()


def _write_prefs_doc(data: dict) -> None:
    from repositories.sqlite_store import SqliteStore

    SqliteStore("test-novel").save_doc("author_loop_skill_prefs", "", data)


def _read_prefs_doc() -> dict:
    from repositories.sqlite_store import SqliteStore

    data = SqliteStore("test-novel").get_doc("author_loop_skill_prefs", "")
    return data if isinstance(data, dict) else {}


def _write_corrupt_prefs_doc(raw: str) -> None:
    from sqlalchemy import text
    from repositories.engine import engine_for_novel

    engine = engine_for_novel("test-novel")
    with engine.connect() as conn:
        conn.execute(
            text("INSERT OR REPLACE INTO documents (doc_key, data_json) VALUES ('author_loop_skill_prefs', :raw)"),
            {"raw": raw},
        )
        conn.commit()



def test_load_dialogue_prefs_missing_returns_defaults():
    assert sp.load_dialogue_prefs() == {
        "target_words": sp.DEFAULT_TARGET_WORDS,
        "disabled_buildtime_review_hooks": [], "disabled_runtime_review_hooks": [], "disabled_setup_review_hooks": [],
        "llm_params": {}, "sandbox_llm_params": {}, "import_llm_params": {},
        "auto_build_character_count": sp.DEFAULT_AUTO_BUILD_CHARACTER_COUNT,
        "auto_build_chapter_count": sp.DEFAULT_AUTO_BUILD_CHAPTER_COUNT,
        "chat_identity": "",
        "recall_cooldown_turns": sp.DEFAULT_RECALL_COOLDOWN_TURNS,
        "recall_top_k": sp.DEFAULT_RECALL_TOP_K,
        "portrait_style_prompt": "", "portrait_negative_prompt": "",
        "portrait_style_preset_id": "anime",
    }


def test_save_dialogue_prefs_target_words_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"target_words": 4500})
    assert sp.load_dialogue_prefs() == {
        "target_words": 4500,
        "disabled_buildtime_review_hooks": [], "disabled_runtime_review_hooks": [], "disabled_setup_review_hooks": [],
        "llm_params": {}, "sandbox_llm_params": {}, "import_llm_params": {},
        "auto_build_character_count": sp.DEFAULT_AUTO_BUILD_CHARACTER_COUNT,
        "auto_build_chapter_count": sp.DEFAULT_AUTO_BUILD_CHAPTER_COUNT,
        "chat_identity": "",
        "recall_cooldown_turns": sp.DEFAULT_RECALL_COOLDOWN_TURNS,
        "recall_top_k": sp.DEFAULT_RECALL_TOP_K,
        "portrait_style_prompt": "", "portrait_negative_prompt": "",
        "portrait_style_preset_id": "anime",
    }


def test_load_corrupt_returns_defaults():
    _write_corrupt_prefs_doc("NOT JSON")
    assert sp.load_dialogue_prefs() == {
        "target_words": sp.DEFAULT_TARGET_WORDS,
        "disabled_buildtime_review_hooks": [], "disabled_runtime_review_hooks": [], "disabled_setup_review_hooks": [],
        "llm_params": {}, "sandbox_llm_params": {}, "import_llm_params": {},
        "auto_build_character_count": sp.DEFAULT_AUTO_BUILD_CHARACTER_COUNT,
        "auto_build_chapter_count": sp.DEFAULT_AUTO_BUILD_CHAPTER_COUNT,
        "chat_identity": "",
        "recall_cooldown_turns": sp.DEFAULT_RECALL_COOLDOWN_TURNS,
        "recall_top_k": sp.DEFAULT_RECALL_TOP_K,
        "portrait_style_prompt": "", "portrait_negative_prompt": "",
        "portrait_style_preset_id": "anime",
    }


def test_save_dialogue_prefs_ignores_non_positive_target_words(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"target_words": 0})
    assert sp.load_dialogue_prefs()["target_words"] == sp.DEFAULT_TARGET_WORDS


def test_save_dialogue_prefs_auto_build_character_count_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"auto_build_character_count": 8})
    assert sp.load_dialogue_prefs()["auto_build_character_count"] == 8


def test_save_dialogue_prefs_ignores_non_positive_auto_build_character_count(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"auto_build_character_count": 0})
    assert sp.load_dialogue_prefs()["auto_build_character_count"] == sp.DEFAULT_AUTO_BUILD_CHARACTER_COUNT


def test_save_dialogue_prefs_auto_build_chapter_count_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"auto_build_chapter_count": 12})
    assert sp.load_dialogue_prefs()["auto_build_chapter_count"] == 12


def test_save_dialogue_prefs_ignores_non_positive_auto_build_chapter_count(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"auto_build_chapter_count": -1})
    assert sp.load_dialogue_prefs()["auto_build_chapter_count"] == sp.DEFAULT_AUTO_BUILD_CHAPTER_COUNT


def test_save_dialogue_prefs_strips_dead_top_level_keys():
    _write_prefs_doc({
        "self_review": {"enabled": True, "threshold": 7},
        "profile_kind": "dialogue",
        "expansion": ["dialogue", "foreplay"],
        "dialogue": {"prose_style": "plain-explicit"},
    })
    sp.save_dialogue_prefs({"target_words": sp.DEFAULT_TARGET_WORDS})
    doc = _read_prefs_doc()
    assert set(doc.keys()) == {"dialogue"}
    assert doc["dialogue"] == {
        "target_words": sp.DEFAULT_TARGET_WORDS,
        "disabled_buildtime_review_hooks": [], "disabled_runtime_review_hooks": [], "disabled_setup_review_hooks": [],
        "llm_params": {}, "sandbox_llm_params": {}, "import_llm_params": {},
        "auto_build_character_count": sp.DEFAULT_AUTO_BUILD_CHARACTER_COUNT,
        "auto_build_chapter_count": sp.DEFAULT_AUTO_BUILD_CHAPTER_COUNT,
        "chat_identity": "",
        "recall_cooldown_turns": sp.DEFAULT_RECALL_COOLDOWN_TURNS,
        "recall_top_k": sp.DEFAULT_RECALL_TOP_K,
        "portrait_style_prompt": "", "portrait_negative_prompt": "",
        "portrait_style_preset_id": "anime",
    }


def test_load_dialogue_prefs_disabled_buildtime_review_hooks_defaults_to_empty(monkeypatch, tmp_path):
    assert sp.load_dialogue_prefs()["disabled_buildtime_review_hooks"] == []


def test_save_dialogue_prefs_disabled_buildtime_review_hooks_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"disabled_buildtime_review_hooks": ["style", "legacy_hook"]})
    assert sp.load_dialogue_prefs()["disabled_buildtime_review_hooks"] == ["style", "legacy_hook"]


def test_load_dialogue_prefs_ignores_non_str_disabled_buildtime_review_hooks():
    _write_prefs_doc({"dialogue": {"disabled_buildtime_review_hooks": ["ok", 1, None, "also-ok"]}})
    assert sp.load_dialogue_prefs()["disabled_buildtime_review_hooks"] == ["ok", "also-ok"]


def test_load_dialogue_prefs_disabled_setup_review_hooks_defaults_to_empty(monkeypatch, tmp_path):
    assert sp.load_dialogue_prefs()["disabled_setup_review_hooks"] == []


def test_save_dialogue_prefs_disabled_setup_review_hooks_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"disabled_setup_review_hooks": ["setup_world_completeness"]})
    assert sp.load_dialogue_prefs()["disabled_setup_review_hooks"] == ["setup_world_completeness"]


def test_load_dialogue_prefs_ignores_non_str_disabled_setup_review_hooks():
    _write_prefs_doc({"dialogue": {"disabled_setup_review_hooks": ["ok", 1, None, "also-ok"]}})
    assert sp.load_dialogue_prefs()["disabled_setup_review_hooks"] == ["ok", "also-ok"]


def test_import_llm_params_setup_quality_review_node_roundtrip(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"import_llm_params": {"setup_quality_review": {"temperature": 0.3}}})
    assert sp.load_dialogue_prefs()["import_llm_params"] == {
        "setup_quality_review": {"temperature": 0.3},
    }


def test_import_llm_params_fix_agent_nodes_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({
        "import_llm_params": {
            "character_fix_agent": {"model_ref": "some-model"},
            "world_fix_agent": {"thinking_effort": "low"},
            "chapter_skeleton_fix_agent": {"temperature": 0.4},
        },
    })
    assert sp.load_dialogue_prefs()["import_llm_params"] == {
        "character_fix_agent": {"model_ref": "some-model"},
        "world_fix_agent": {"thinking_effort": "low"},
        "chapter_skeleton_fix_agent": {"temperature": 0.4},
    }


def test_load_dialogue_prefs_disabled_runtime_review_hooks_defaults_to_empty(monkeypatch, tmp_path):
    assert sp.load_dialogue_prefs()["disabled_runtime_review_hooks"] == []


def test_save_dialogue_prefs_disabled_runtime_review_hooks_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"disabled_runtime_review_hooks": ["fidelity"]})
    assert sp.load_dialogue_prefs()["disabled_runtime_review_hooks"] == ["fidelity"]


def test_load_dialogue_prefs_ignores_non_str_disabled_runtime_review_hooks():
    _write_prefs_doc({"dialogue": {"disabled_runtime_review_hooks": ["ok", 1, None, "also-ok"]}})
    assert sp.load_dialogue_prefs()["disabled_runtime_review_hooks"] == ["ok", "also-ok"]


def test_save_dialogue_prefs_buildtime_and_runtime_hooks_are_independent(monkeypatch, tmp_path):
    """两组禁用列表各自独立写入,互不覆盖。"""
    sp.save_dialogue_prefs({"disabled_buildtime_review_hooks": ["style"]})
    sp.save_dialogue_prefs({"disabled_runtime_review_hooks": ["fidelity"]})
    prefs = sp.load_dialogue_prefs()
    assert prefs["disabled_buildtime_review_hooks"] == ["style"]
    assert prefs["disabled_runtime_review_hooks"] == ["fidelity"]


def test_load_dialogue_prefs_llm_params_defaults_to_empty(monkeypatch, tmp_path):
    assert sp.load_dialogue_prefs()["llm_params"] == {}


def test_save_dialogue_prefs_llm_params_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"llm_params": {"director": {"temperature": 0.8, "top_p": 0.95}}})
    assert sp.load_dialogue_prefs()["llm_params"] == {
        "director": {"temperature": 0.8, "top_p": 0.95},
    }


def test_save_dialogue_prefs_llm_params_drops_unknown_node_id(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"llm_params": {"not-a-real-node": {"temperature": 0.8}}})
    assert sp.load_dialogue_prefs()["llm_params"] == {}


def test_save_dialogue_prefs_llm_params_drops_out_of_range_and_unknown_keys(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"llm_params": {
        "director": {"temperature": 3.0, "top_p": 0.9, "logit_bias": {"123": -100}},
    }})
    assert sp.load_dialogue_prefs()["llm_params"] == {"director": {"top_p": 0.9}}


def test_save_dialogue_prefs_llm_params_bool_is_not_treated_as_number(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"llm_params": {"director": {"temperature": True}}})
    assert sp.load_dialogue_prefs()["llm_params"] == {}


def test_sandbox_llm_params_round_trip(monkeypatch, tmp_path):
    """沙盒 tab 的 6 节点采样参数需要独立于运行时 llm_params 落盘/读回。"""
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"sandbox_llm_params": {"prose": {"temperature": 1.1}}})
    out = sp.load_dialogue_prefs()
    assert out["sandbox_llm_params"] == {"prose": {"temperature": 1.1}}
    assert out["llm_params"] == {}


def test_sandbox_llm_params_rejects_unknown_node(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({
        "sandbox_llm_params": {"director": {"temperature": 1.0}, "prose": {"temperature": 0.9}},
    })
    out = sp.load_dialogue_prefs()
    assert out["sandbox_llm_params"] == {"prose": {"temperature": 0.9}}


def test_resolve_node_llm_params_returns_empty_for_unconfigured_node():
    assert sp.resolve_node_llm_params("director", {}) == {}


class _FakeLlm:
    def __init__(self):
        self.bound_with: dict | None = None

    def bind(self, **kwargs):
        self.bound_with = kwargs
        return "BOUND"


def test_bind_node_llm_binds_when_params_configured():
    llm = _FakeLlm()
    result = sp.bind_node_llm(llm, "director", {"director": {"temperature": 0.8}})
    assert result == "BOUND"
    assert llm.bound_with == {"temperature": 0.8}


def test_bind_node_llm_unconfigured_core_node_defaults_thinking_on():
    llm = _FakeAnthropic()
    bound = sp.bind_node_llm(llm, "director", {})
    assert bound.kwargs == {"thinking": {"type": "enabled", "budget_tokens": 4096}}


def test_bind_node_llm_unconfigured_auxiliary_node_defaults_thinking_off_on_deepseek():
    llm = _FakeOpenAICompatible()
    bound = sp.bind_node_llm(llm, "state_derive", {})
    assert bound.kwargs == {
        "extra_body": {"thinking": {"type": "disabled"}},
        "reasoning_effort": "none",
    }


def test_default_enable_thinking_for_node_core_and_auxiliary():
    assert sp.default_enable_thinking_for_node("director") is True
    assert sp.default_enable_thinking_for_node("prose") is True
    assert sp.default_enable_thinking_for_node("dialogue_draft") is False
    assert sp.default_enable_thinking_for_node("dialogue") is False
    assert sp.default_enable_thinking_for_node("author_prose") is False
    assert sp.default_enable_thinking_for_node("chat_identity") is True
    assert sp.default_enable_thinking_for_node("state_derive") is False
    assert sp.default_enable_thinking_for_node("detail:onomatopoeia") is False
    assert sp.default_enable_thinking_for_node("text_recognition") is False
    assert sp.default_enable_thinking_for_node("character_fix_agent") is True
    assert sp.default_enable_thinking_for_node("world_fix_agent") is True
    assert sp.default_enable_thinking_for_node("chapter_skeleton_fix_agent") is True


def test_default_thinking_effort_for_node_fix_agents_high_others_medium():
    assert sp.default_thinking_effort_for_node("character_fix_agent") == ThinkingEffort.HIGH
    assert sp.default_thinking_effort_for_node("world_fix_agent") == ThinkingEffort.HIGH
    assert sp.default_thinking_effort_for_node("chapter_skeleton_fix_agent") == ThinkingEffort.HIGH
    assert sp.default_thinking_effort_for_node("director") == ThinkingEffort.MEDIUM


def test_bind_node_llm_unconfigured_fix_agent_defaults_thinking_high():
    llm = _FakeAnthropic()
    bound = sp.bind_node_llm(llm, "character_fix_agent", {})
    assert bound.kwargs == {"thinking": {"type": "enabled", "budget_tokens": 16000}}


def test_save_dialogue_prefs_llm_params_enable_thinking_and_effort_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({
        "llm_params": {"director": {"temperature": 0.8, "enable_thinking": True, "thinking_effort": "high"}},
    })
    assert sp.load_dialogue_prefs()["llm_params"] == {
        "director": {"temperature": 0.8, "enable_thinking": True, "thinking_effort": "high"},
    }


def test_save_dialogue_prefs_llm_params_drops_invalid_thinking_effort(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({
        "llm_params": {"director": {"enable_thinking": True, "thinking_effort": "extreme"}},
    })
    assert sp.load_dialogue_prefs()["llm_params"] == {"director": {"enable_thinking": True}}


def test_save_dialogue_prefs_llm_params_drops_non_bool_enable_thinking(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"llm_params": {"director": {"enable_thinking": "yes"}}})
    assert sp.load_dialogue_prefs()["llm_params"] == {}


class _FakeAnthropic(ChatAnthropic):
    def __init__(self):
        super().__init__(model="claude-3-5-haiku-latest", api_key="test-key")


class _FakeOpenAICompatible(ChatOpenAI):
    def __init__(self):
        super().__init__(model="deepseek-v4-flash", api_key="test-key")


def test_bind_node_llm_enable_thinking_true_binds_anthropic_thinking_kwarg():
    llm = _FakeAnthropic()
    bound = sp.bind_node_llm(
        llm, "director",
        {"director": {"temperature": 0.8, "enable_thinking": True, "thinking_effort": "high"}},
    )
    assert bound.kwargs == {
        "temperature": 0.8,
        "thinking": {"type": "enabled", "budget_tokens": 16000},
    }


def test_bind_node_llm_enable_thinking_true_binds_openai_compatible_reasoning_effort():
    llm = _FakeOpenAICompatible()
    bound = sp.bind_node_llm(
        llm, "prose", {"prose": {"enable_thinking": True, "thinking_effort": "low"}},
    )
    assert bound.kwargs == {
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "low",
    }


def test_bind_node_llm_enable_thinking_true_without_effort_defaults_to_medium():
    llm = _FakeAnthropic()
    bound = sp.bind_node_llm(llm, "director", {"director": {"enable_thinking": True}})
    assert bound.kwargs == {"thinking": {"type": "enabled", "budget_tokens": 4096}}


def test_bind_node_llm_enable_thinking_false_binds_disable_kwargs():
    llm = _FakeAnthropic()
    bound = sp.bind_node_llm(llm, "director", {"director": {"enable_thinking": False}})
    assert bound.kwargs == {"thinking": {"type": "disabled"}}


def test_bind_node_llm_enable_thinking_false_deepseek_binds_disable_kwargs():
    llm = _FakeOpenAICompatible()
    bound = sp.bind_node_llm(llm, "director", {"director": {"enable_thinking": False}})
    assert bound.kwargs == {
        "extra_body": {"thinking": {"type": "disabled"}},
        "reasoning_effort": "none",
    }


def test_save_dialogue_prefs_llm_params_provider_local_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({
        "llm_params": {"director": {
            "provider": "local", "base_url": "http://localhost:1234/v1", "model": "qwen3-8b",
        }},
    })
    assert sp.load_dialogue_prefs()["llm_params"] == {
        "director": {"provider": "local", "base_url": "http://localhost:1234/v1", "model": "qwen3-8b"},
    }


def test_save_dialogue_prefs_llm_params_provider_local_missing_base_url_keeps_partial_override(monkeypatch, tmp_path):
    """provider/base_url/model persist independently (like enable_thinking/thinking_effort)
    so an in-progress edit round-trips intact -- only bind_node_llm's own completeness check
    gates whether an incomplete override actually takes effect at call time."""
    sp.save_dialogue_prefs({
        "llm_params": {"director": {"provider": "local", "model": "qwen3-8b", "temperature": 0.8}},
    })
    assert sp.load_dialogue_prefs()["llm_params"] == {
        "director": {"temperature": 0.8, "provider": "local", "model": "qwen3-8b"},
    }


def test_save_dialogue_prefs_llm_params_provider_local_missing_model_keeps_partial_override(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({
        "llm_params": {"director": {"provider": "local", "base_url": "http://localhost:1234/v1"}},
    })
    assert sp.load_dialogue_prefs()["llm_params"] == {
        "director": {"provider": "local", "base_url": "http://localhost:1234/v1"},
    }


def test_save_dialogue_prefs_llm_params_provider_local_alone_keeps_provider(monkeypatch, tmp_path):
    """Regression test: the moment a user picks 'local' in the UI dropdown -- before typing
    base_url/model -- provider must still round-trip, or the dropdown silently snaps back to
    'cloud' on the next refetch and the base_url/model inputs never appear."""
    sp.save_dialogue_prefs({"llm_params": {"director": {"provider": "local"}}})
    assert sp.load_dialogue_prefs()["llm_params"] == {"director": {"provider": "local"}}


def test_save_dialogue_prefs_llm_params_provider_cloud_writes_nothing(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({
        "llm_params": {"director": {"provider": "cloud", "temperature": 0.8}},
    })
    assert sp.load_dialogue_prefs()["llm_params"] == {"director": {"temperature": 0.8}}


def test_save_dialogue_prefs_llm_params_provider_unknown_value_dropped(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({
        "llm_params": {"director": {"provider": "openai", "base_url": "x", "model": "y", "temperature": 0.8}},
    })
    assert sp.load_dialogue_prefs()["llm_params"] == {"director": {"temperature": 0.8}}


def test_sandbox_llm_params_provider_local_roundtrip(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({
        "sandbox_llm_params": {"prose": {
            "provider": "local", "base_url": "http://localhost:1234/v1", "model": "qwen3-8b",
        }},
    })
    assert sp.load_dialogue_prefs()["sandbox_llm_params"] == {
        "prose": {"provider": "local", "base_url": "http://localhost:1234/v1", "model": "qwen3-8b"},
    }


class _FakeLocalLlm:
    def __init__(self):
        self.bound_with: dict | None = None

    def bind(self, **kwargs):
        self.bound_with = kwargs
        return "LOCAL_BOUND"


def test_bind_node_llm_provider_local_switches_base_llm(monkeypatch):
    import llm.factory as factory
    local_llm = _FakeLocalLlm()
    captured_args = {}

    def fake_get_node_local_llm(base_url, model):
        captured_args["base_url"] = base_url
        captured_args["model"] = model
        return local_llm

    monkeypatch.setattr(factory, "get_node_local_llm", fake_get_node_local_llm)
    llm = _FakeLlm()
    result = sp.bind_node_llm(
        llm, "prose",
        {"prose": {
            "provider": "local", "base_url": "http://localhost:1234/v1", "model": "qwen3-8b",
            "temperature": 0.9,
        }},
    )
    assert result == "LOCAL_BOUND"
    assert local_llm.bound_with == {"temperature": 0.9}
    assert llm.bound_with is None
    assert captured_args == {"base_url": "http://localhost:1234/v1", "model": "qwen3-8b"}


def test_bind_node_llm_provider_local_incomplete_override_falls_back_to_cloud():
    """Defense in depth: even if a caller bypasses _clean_llm_params and hands bind_node_llm
    a raw dict with provider=local but a missing base_url/model, it must not switch clients."""
    llm = _FakeLlm()
    result = sp.bind_node_llm(llm, "prose", {"prose": {"provider": "local", "temperature": 0.9}})
    assert result == "BOUND"
    assert llm.bound_with == {"temperature": 0.9}


def test_bind_node_llm_provider_cloud_uses_original_llm():
    llm = _FakeLlm()
    result = sp.bind_node_llm(llm, "prose", {"prose": {"provider": "cloud", "temperature": 0.5}})
    assert result == "BOUND"
    assert llm.bound_with == {"temperature": 0.5}


def test_bind_node_llm_provider_local_with_thinking_dispatches_on_local_client_type(monkeypatch):
    """enable_thinking's provider dispatch must key off the NEW base (local), not the
    original cloud llm passed in -- a ChatOpenAI-shaped local override should still get
    reasoning_effort, matching OpenAICompatibleThinkingResolver's isinstance(ChatOpenAI) branch."""
    import llm.factory as factory
    from langchain_openai import ChatOpenAI

    class _FakeLocalOpenAI(ChatOpenAI):
        def __init__(self):
            super().__init__(model="qwen3-8b", api_key="lm-studio", base_url="http://localhost:1234/v1")

    local_llm = _FakeLocalOpenAI()
    monkeypatch.setattr(factory, "get_node_local_llm", lambda base_url, model: local_llm)
    llm = _FakeAnthropic()
    bound = sp.bind_node_llm(
        llm, "prose",
        {"prose": {
            "provider": "local", "base_url": "http://localhost:1234/v1", "model": "qwen3-8b",
            "enable_thinking": True, "thinking_effort": "low",
        }},
    )
    assert bound.kwargs == {"reasoning_effort": "low"}


def test_save_dialogue_prefs_llm_params_disable_style_guard_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({
        "llm_params": {"director": {"temperature": 0.8, "disable_style_guard": True}},
    })
    assert sp.load_dialogue_prefs()["llm_params"] == {
        "director": {"temperature": 0.8, "disable_style_guard": True},
    }


def test_save_dialogue_prefs_llm_params_disable_style_guard_rejected_outside_director(monkeypatch, tmp_path):
    """review/state_derive never run the style guard architecturally --
    disable_style_guard is silently dropped there even though the value itself is valid."""
    sp.save_dialogue_prefs({
        "llm_params": {"review": {"temperature": 0.5, "disable_style_guard": True}},
    })
    assert sp.load_dialogue_prefs()["llm_params"] == {"review": {"temperature": 0.5}}


def test_save_dialogue_prefs_llm_params_disable_style_guard_rejects_non_bool(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({
        "llm_params": {"director": {"disable_style_guard": "yes"}},
    })
    assert sp.load_dialogue_prefs()["llm_params"] == {}


def test_sandbox_llm_params_disable_style_guard_roundtrip_all_sandbox_nodes(monkeypatch, tmp_path):
    """All sandbox nodes run guard architecturally -- disable_style_guard is honored on
    every one of them, unlike llm_params where only director qualifies."""
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({
        "sandbox_llm_params": {
            "prose": {"disable_style_guard": True},
            "derive_char": {"disable_style_guard": True},
            "derive_scene": {"disable_style_guard": True},
            "summary_fold": {"disable_style_guard": True},
            "event_extract": {"disable_style_guard": True},
            "profile_mutate": {"disable_style_guard": True},
            "suggest": {"disable_style_guard": True},
        },
    })
    assert sp.load_dialogue_prefs()["sandbox_llm_params"] == {
        "prose": {"disable_style_guard": True},
        "derive_char": {"disable_style_guard": True},
        "derive_scene": {"disable_style_guard": True},
        "summary_fold": {"disable_style_guard": True},
        "event_extract": {"disable_style_guard": True},
        "profile_mutate": {"disable_style_guard": True},
        "suggest": {"disable_style_guard": True},
    }


def test_sandbox_llm_params_filters_legacy_event_log_key(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({
        "sandbox_llm_params": {
            "event_log": {"enable_thinking": False, "disable_style_guard": True},
            "summary_fold": {"enable_thinking": True},
            "event_extract": {"thinking_effort": "low"},
        },
    })
    assert sp.load_dialogue_prefs()["sandbox_llm_params"] == {
        "summary_fold": {"enable_thinking": True},
        "event_extract": {"thinking_effort": "low"},
    }


def test_bind_node_llm_disable_style_guard_does_not_leak_into_bind_kwargs():
    """disable_style_guard is consumed directly by message_hub.py, never through
    bind_node_llm -- it must still be popped out before .bind(**params), or it would be
    passed as an invalid kwarg to the underlying LangChain client."""
    llm = _FakeLlm()
    result = sp.bind_node_llm(
        llm, "director", {"director": {"temperature": 0.8, "disable_style_guard": True}},
    )
    assert result == "BOUND"
    assert llm.bound_with == {"temperature": 0.8}


def test_clean_llm_params_model_ref_string_kept(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"llm_params": {"director": {"model_ref": "deepseek-v4-flash"}}})
    assert sp.load_dialogue_prefs()["llm_params"] == {"director": {"model_ref": "deepseek-v4-flash"}}


def test_clean_llm_params_model_ref_non_string_dropped(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"llm_params": {"director": {"model_ref": 123, "temperature": 0.5}}})
    assert sp.load_dialogue_prefs()["llm_params"] == {"director": {"temperature": 0.5}}


def test_clean_llm_params_model_ref_empty_string_dropped(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"llm_params": {"director": {"model_ref": "", "temperature": 0.5}}})
    assert sp.load_dialogue_prefs()["llm_params"] == {"director": {"temperature": 0.5}}


def test_bind_node_llm_model_ref_resolves_via_registry(monkeypatch):
    llm = object()
    entry = {"id": "custom-1", "model": "m1", "base_url": "https://x.example.com/v1", "provider": "openai_compatible"}
    bound_llm = object()
    monkeypatch.setattr(
        "domain.model_catalog.resolve_model_entry",
        lambda entry_id, custom_models=None: entry if entry_id == "custom-1" else None,
    )
    monkeypatch.setattr("llm.factory.get_registry_llm", lambda e: bound_llm if e is entry else None)
    result = sp.bind_node_llm(llm, "director", {"director": {"model_ref": "custom-1"}})
    assert result is bound_llm


def test_bind_node_llm_model_ref_unknown_id_falls_back_to_global(monkeypatch):
    llm = object()
    monkeypatch.setattr("domain.model_catalog.resolve_model_entry", lambda entry_id, custom_models=None: None)
    result = sp.bind_node_llm(llm, "director", {"director": {"model_ref": "does-not-exist"}})
    assert result is llm


def test_bind_node_llm_model_ref_takes_priority_over_legacy_provider(monkeypatch):
    llm = object()
    entry = {"id": "custom-1", "model": "m1", "base_url": "https://x.example.com/v1", "provider": "openai_compatible"}
    bound_llm = object()
    monkeypatch.setattr(
        "domain.model_catalog.resolve_model_entry",
        lambda entry_id, custom_models=None: entry if entry_id == "custom-1" else None,
    )
    monkeypatch.setattr("llm.factory.get_registry_llm", lambda e: bound_llm if e is entry else None)
    result = sp.bind_node_llm(
        llm, "prose",
        {"prose": {
            "model_ref": "custom-1",
            "provider": "local", "base_url": "http://localhost:1234/v1", "model": "qwen3-8b",
        }},
    )
    assert result is bound_llm


def test_import_llm_params_round_trip(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"import_llm_params": {"image_recognition": {"model_ref": "custom-vision-1"}}})
    out = sp.load_dialogue_prefs()
    assert out["import_llm_params"] == {"image_recognition": {"model_ref": "custom-vision-1"}}
    assert out["llm_params"] == {}
    assert out["sandbox_llm_params"] == {}


def test_import_llm_params_merges_legacy_image_batch_consolidator():
    _write_prefs_doc({
        "dialogue": {
            "import_llm_params": {
                "image_batch_consolidator": {"model_ref": "legacy-consolidator", "temperature": 0.2},
                "image_recognition": {"model_ref": "custom-vision-1", "top_p": 0.9},
            },
        },
    })
    out = sp.load_dialogue_prefs()
    assert out["import_llm_params"] == {
        "image_recognition": {"model_ref": "custom-vision-1", "temperature": 0.2, "top_p": 0.9},
    }
    assert "image_batch_consolidator" not in out["import_llm_params"]


def test_resolve_image_recognition_params_prefers_image_recognition_on_conflict():
    merged = sp.resolve_image_recognition_params({
        "image_batch_consolidator": {"model_ref": "legacy", "temperature": 0.1},
        "image_recognition": {"model_ref": "current", "temperature": 0.9},
    })
    assert merged == {"model_ref": "current", "temperature": 0.9}


def test_is_image_recognition_configured(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    assert sp.is_image_recognition_configured() is False
    sp.save_dialogue_prefs({"import_llm_params": {"image_recognition": {"model_ref": "custom-vision-1"}}})
    assert sp.is_image_recognition_configured() is True


def test_import_llm_params_rejects_unknown_node(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"import_llm_params": {"not-a-real-node": {"model_ref": "x"}}})
    assert sp.load_dialogue_prefs()["import_llm_params"] == {}


def test_import_llm_params_both_nodes_independent(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"import_llm_params": {
        "text_recognition": {"model_ref": "deepseek-v4-flash"},
        "image_recognition": {"model_ref": "custom-vision-1"},
    }})
    assert sp.load_dialogue_prefs()["import_llm_params"] == {
        "text_recognition": {"model_ref": "deepseek-v4-flash"},
        "image_recognition": {"model_ref": "custom-vision-1"},
    }


def test_import_llm_params_chat_identity_node_roundtrip(monkeypatch, tmp_path):
    """chat_identity is whitelisted alongside image/text_recognition -- the setup_chat
    main agent node now takes LLM sampling-param/model_ref overrides the same way the
    two recognition capability nodes already do (see engine.setup_chat.agent._bind_chat_model)."""
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"import_llm_params": {"chat_identity": {"temperature": 0.4}}})
    assert sp.load_dialogue_prefs()["import_llm_params"] == {"chat_identity": {"temperature": 0.4}}


def test_import_llm_params_review_node_roundtrip(monkeypatch, tmp_path):
    """review (对话 tab 的文风/过渡审查节点) is whitelisted alongside chat_identity/image/
    text_recognition -- chapter_review.py::_review_llm now takes the same enable_thinking/
    model_ref overrides its three sibling capability nodes already do."""
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"import_llm_params": {"review": {"enable_thinking": False}}})
    assert sp.load_dialogue_prefs()["import_llm_params"] == {"review": {"enable_thinking": False}}


def test_import_llm_params_auto_build_setup_node_roundtrip(monkeypatch, tmp_path):
    """auto_build_setup (对话 tab 的一键建设定节点) is whitelisted alongside its four sibling
    capability nodes -- tools.py::auto_build_setup now takes the same sampling-param/model_ref
    overrides they already do (previously called get_cloud_llm() with no node override at all)."""
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"import_llm_params": {"auto_build_setup": {"model_ref": "custom-1"}}})
    assert sp.load_dialogue_prefs()["import_llm_params"] == {"auto_build_setup": {"model_ref": "custom-1"}}


def test_import_llm_params_timeline_derive_node_roundtrip(monkeypatch, tmp_path):
    """timeline_derive (对话 tab 的角色档案自动推演节点) is whitelisted alongside its five sibling
    capability nodes -- timeline_auto.py::_call_llm now takes the same sampling-param/model_ref
    overrides they already do (previously called get_cloud_llm() with no node override at all)."""
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"import_llm_params": {"timeline_derive": {"enable_thinking": False}}})
    assert sp.load_dialogue_prefs()["import_llm_params"] == {"timeline_derive": {"enable_thinking": False}}


def test_import_llm_params_skeleton_internal_nodes_roundtrip(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"import_llm_params": {
        "skeleton_writer": {"enable_thinking": False},
        "beat_dialogue_draft": {"enable_thinking": False},
        "prose_style_extraction": {"temperature": 0.2},
        "incremental_relationship": {"model_ref": "custom-1"},
    }})
    assert sp.load_dialogue_prefs()["import_llm_params"] == {
        "skeleton_writer": {"enable_thinking": False},
        "beat_dialogue_draft": {"enable_thinking": False},
        "prose_style_extraction": {"temperature": 0.2},
        "incremental_relationship": {"model_ref": "custom-1"},
    }


@pytest.mark.asyncio
async def test_beat_dialogue_draft_call_llm_routes_through_import_node(monkeypatch):
    """Lives outside tests/engine/setup_chat/ so conftest's autouse _stub_dialogue_draft
    doesn't replace _call_llm before we can exercise the bind path."""
    from engine.setup_chat import dialogue_draft as dd

    class _FakeResp:
        content = "台词"

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _FakeResp()

    bind_calls: list[tuple[str, dict]] = []

    def fake_bind_node_llm(llm, agent, params):
        bind_calls.append((agent, params))
        return _FakeLLM()

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())
    monkeypatch.setattr(
        sp, "load_dialogue_prefs",
        lambda: {"import_llm_params": {"beat_dialogue_draft": {"enable_thinking": False}}},
    )
    monkeypatch.setattr(sp, "bind_node_llm", fake_bind_node_llm)

    out = await dd._call_llm("sys", "user")
    assert out == "台词"
    assert bind_calls == [("beat_dialogue_draft", {"beat_dialogue_draft": {"enable_thinking": False}})]


def test_resolve_node_base_llm_returns_unchanged_without_model_ref():
    sentinel = object()
    assert sp.resolve_node_base_llm(sentinel, "chat_identity", {}) is sentinel


def test_node_llm_sampling_kwargs_applies_default_thinking_for_chat_identity():
    kwargs = sp.node_llm_sampling_kwargs(_FakeAnthropic(), "chat_identity", {})
    assert kwargs == {"thinking": {"type": "enabled", "budget_tokens": 4096}}


def test_node_llm_sampling_kwargs_empty_when_unconfigured_auxiliary_node():
    kwargs = sp.node_llm_sampling_kwargs(_FakeAnthropic(), "state_derive", {})
    assert kwargs == {"thinking": {"type": "disabled"}}


def test_node_llm_sampling_kwargs_extracts_temperature():
    kwargs = sp.node_llm_sampling_kwargs(
        object(), "chat_identity", {"chat_identity": {"temperature": 0.55}},
    )
    assert kwargs == {"temperature": 0.55}


def test_bind_node_llm_still_composes_swap_and_sampling_kwargs(monkeypatch):
    """Regression: bind_node_llm's net behavior must stay identical after being split
    into resolve_node_base_llm + node_llm_sampling_kwargs."""
    class _Bound:
        def __init__(self, base, kwargs):
            self.base = base
            self.kwargs = kwargs

    class _Llm:
        def bind(self, **kwargs):
            return _Bound(self, kwargs)

    llm = _Llm()
    result = sp.bind_node_llm(llm, "chat_identity", {"chat_identity": {"temperature": 0.2}})
    assert result.base is llm
    assert result.kwargs == {"temperature": 0.2}


def test_save_dialogue_prefs_chat_identity_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"chat_identity": "  你是一个自定义身份  "})
    assert sp.load_dialogue_prefs()["chat_identity"] == "你是一个自定义身份"


def test_sandbox_llm_params_dialogue_draft_and_identify_cast_roundtrip(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"sandbox_llm_params": {
        "dialogue_draft": {"enable_thinking": False, "thinking_effort": "low", "model_ref": "deepseek-v4-flash"},
        "identify_cast": {"enable_thinking": True, "thinking_effort": "high", "temperature": 0.5},
    }})
    out = sp.load_dialogue_prefs()["sandbox_llm_params"]
    assert out["dialogue_draft"] == {
        "enable_thinking": False, "thinking_effort": "low", "model_ref": "deepseek-v4-flash",
    }
    assert out["identify_cast"] == {
        "enable_thinking": True, "thinking_effort": "high", "temperature": 0.5,
    }


def test_sandbox_llm_params_derive_char_concurrent_roundtrip(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"sandbox_llm_params": {
        "derive_char": {"concurrent": True},
        "prose": {"concurrent": True},
    }})
    out = sp.load_dialogue_prefs()["sandbox_llm_params"]
    assert out == {"derive_char": {"concurrent": True}}


def test_sandbox_llm_params_dialogue_draft_disable_style_guard_filtered(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"sandbox_llm_params": {
        "dialogue_draft": {"disable_style_guard": True, "temperature": 0.8},
        "identify_cast": {"disable_style_guard": True, "enable_thinking": False},
    }})
    out = sp.load_dialogue_prefs()["sandbox_llm_params"]
    assert out["dialogue_draft"] == {"temperature": 0.8}
    assert out["identify_cast"] == {"enable_thinking": False}


def test_bind_node_llm_dialogue_draft_enable_thinking_false_binds_disable_kwargs():
    llm = _FakeOpenAICompatible()
    bound = sp.bind_node_llm(
        llm, "dialogue_draft",
        {"dialogue_draft": {"enable_thinking": False}},
    )
    assert bound.kwargs == {
        "extra_body": {"thinking": {"type": "disabled"}},
        "reasoning_effort": "none",
    }


def test_sandbox_llm_params_selection_rewrite_roundtrip(monkeypatch, tmp_path):
    p = tmp_path / "skill_prefs.json"
    sp.save_dialogue_prefs({"sandbox_llm_params": {
        "selection_rewrite": {
            "enable_thinking": False, "thinking_effort": "low", "disable_style_guard": True,
        },
    }})
    out = sp.load_dialogue_prefs()["sandbox_llm_params"]
    assert out["selection_rewrite"] == {
        "enable_thinking": False, "thinking_effort": "low", "disable_style_guard": True,
    }


def test_save_dialogue_prefs_ignores_non_str_chat_identity(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"chat_identity": 123})
    assert sp.load_dialogue_prefs()["chat_identity"] == ""


def test_load_dialogue_prefs_recall_defaults():
    prefs = sp.load_dialogue_prefs()
    assert prefs["recall_cooldown_turns"] == sp.DEFAULT_RECALL_COOLDOWN_TURNS
    assert prefs["recall_top_k"] == sp.DEFAULT_RECALL_TOP_K


def test_save_dialogue_prefs_recall_cooldown_turns_and_top_k_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"recall_cooldown_turns": 20, "recall_top_k": 8})
    prefs = sp.load_dialogue_prefs()
    assert prefs["recall_cooldown_turns"] == 20
    assert prefs["recall_top_k"] == 8


def test_save_dialogue_prefs_ignores_invalid_recall_cooldown_turns(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"recall_cooldown_turns": 0, "recall_top_k": -1})
    prefs = sp.load_dialogue_prefs()
    assert prefs["recall_cooldown_turns"] == sp.DEFAULT_RECALL_COOLDOWN_TURNS
    assert prefs["recall_top_k"] == sp.DEFAULT_RECALL_TOP_K


def test_load_dialogue_prefs_ignores_invalid_recall_fields():
    _write_prefs_doc({
        "dialogue": {
            "recall_cooldown_turns": "20",
            "recall_top_k": 0,
        },
    })
    prefs = sp.load_dialogue_prefs()
    assert prefs["recall_cooldown_turns"] == sp.DEFAULT_RECALL_COOLDOWN_TURNS
    assert prefs["recall_top_k"] == sp.DEFAULT_RECALL_TOP_K


def test_save_dialogue_prefs_portrait_prompts_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({
        "portrait_style_prompt": "  watercolor style  ",
        "portrait_negative_prompt": "  no watermark  ",
    })
    prefs = sp.load_dialogue_prefs()
    assert prefs["portrait_style_prompt"] == "watercolor style"
    assert prefs["portrait_negative_prompt"] == "no watermark"


def test_load_dialogue_prefs_portrait_prompts_default_empty():
    prefs = sp.load_dialogue_prefs()
    assert prefs["portrait_style_prompt"] == ""
    assert prefs["portrait_negative_prompt"] == ""


def test_save_dialogue_prefs_ignores_non_str_portrait_prompts(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"portrait_style_prompt": 123, "portrait_negative_prompt": None})
    prefs = sp.load_dialogue_prefs()
    assert prefs["portrait_style_prompt"] == ""
    assert prefs["portrait_negative_prompt"] == ""


def test_load_dialogue_prefs_portrait_style_preset_id_defaults_to_anime():
    prefs = sp.load_dialogue_prefs()
    assert prefs["portrait_style_preset_id"] == "anime"


def test_save_dialogue_prefs_portrait_style_preset_id_roundtrip(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"portrait_style_preset_id": "cyberpunk"})
    assert sp.load_dialogue_prefs()["portrait_style_preset_id"] == "cyberpunk"


def test_save_dialogue_prefs_blank_or_non_str_preset_id_falls_back_to_anime(monkeypatch, tmp_path):
    sp.save_dialogue_prefs({"portrait_style_preset_id": "cyberpunk"})
    sp.save_dialogue_prefs({"portrait_style_preset_id": "   "})
    assert sp.load_dialogue_prefs()["portrait_style_preset_id"] == "anime"

    sp.save_dialogue_prefs({"portrait_style_preset_id": "cyberpunk"})
    sp.save_dialogue_prefs({"portrait_style_preset_id": 123})
    assert sp.load_dialogue_prefs()["portrait_style_preset_id"] == "cyberpunk"  # non-str ignored, unchanged
