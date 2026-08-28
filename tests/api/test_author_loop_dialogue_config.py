"""author_loop_dialogue_config: read_state/write_config 透传。"""
import api.services.author_loop_dialogue_config as cfg


def test_write_config_passes_through_target_words(monkeypatch):
    saved = {}
    monkeypatch.setattr(cfg, "save_dialogue_prefs", lambda prefs: saved.update(prefs))
    monkeypatch.setattr(cfg, "read_state", lambda: {"ok-marker": True})
    result = cfg.write_config({"dialogue": {"target_words": 5000}})
    assert saved == {"target_words": 5000}
    assert result == {"ok": True, "ok-marker": True}


def test_list_buildtime_review_hooks_marks_axis_and_enabled(monkeypatch):
    class _FakeHook:
        def __init__(self, name, display_name):
            self.name = name
            self.display_name = display_name

    monkeypatch.setattr(
        "engine.author_loop.review.review_loader.REVIEW_HOOKS",
        [_FakeHook("coherence", "衔接判官"), _FakeHook("style", "文风判官")],
    )
    monkeypatch.setattr(
        "engine.setup_chat.chapter_review.TRANSITION_HOOK_NAMES", ("coherence",),
    )
    monkeypatch.setattr(
        "engine.setup_chat.chapter_review.STAGE_HOOK_NAMES", ("style",),
    )
    monkeypatch.setattr(cfg, "load_dialogue_prefs",
                        lambda: {"target_words": 3000,
                                 "disabled_buildtime_review_hooks": ["style"],
                                 "disabled_runtime_review_hooks": []})
    hooks = cfg._list_buildtime_review_hooks()
    assert hooks == [
        {"name": "coherence", "display_name": "衔接判官", "axis": "transition", "enabled": True},
        {"name": "style", "display_name": "文风判官", "axis": "stage", "enabled": False},
    ]


def test_list_runtime_review_hooks_marks_enabled_no_axis(monkeypatch):
    class _FakeHook:
        def __init__(self, name, display_name):
            self.name = name
            self.display_name = display_name

    monkeypatch.setattr(
        "engine.author_loop.review.review_loader.REVIEW_HOOKS",
        [_FakeHook("fidelity", "骨架保真判官"), _FakeHook("expansion_ratio", "扩写倍率"),
         _FakeHook("style", "文风判官")],
    )
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.stage_review.RUNTIME_HOOK_NAMES",
        ("fidelity", "expansion_ratio", "style"),
    )
    monkeypatch.setattr(cfg, "load_dialogue_prefs",
                        lambda: {"target_words": 3000,
                                 "disabled_buildtime_review_hooks": [],
                                 "disabled_runtime_review_hooks": ["expansion_ratio"]})
    hooks = cfg._list_runtime_review_hooks()
    assert hooks == [
        {"name": "fidelity", "display_name": "骨架保真判官", "enabled": True},
        {"name": "expansion_ratio", "display_name": "扩写倍率", "enabled": False},
        {"name": "style", "display_name": "文风判官", "enabled": True},
    ]


def test_list_setup_review_hooks_marks_axis_and_enabled(monkeypatch):
    class _FakeHook:
        def __init__(self, name, display_name):
            self.name = name
            self.display_name = display_name

    monkeypatch.setattr(
        "engine.author_loop.review.review_loader.REVIEW_HOOKS",
        [
            _FakeHook("setup_world_completeness", "设定完整度"),
            _FakeHook("setup_world_tension", "冲突张力"),
        ],
    )
    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.SETUP_WORLD_HOOK_NAMES",
        ("setup_world_completeness",),
    )
    monkeypatch.setattr(cfg, "load_dialogue_prefs",
                        lambda: {"target_words": 3000,
                                 "disabled_buildtime_review_hooks": [],
                                 "disabled_runtime_review_hooks": [],
                                 "disabled_setup_review_hooks": []})
    hooks = cfg._list_setup_review_hooks()
    assert hooks == [
        {"name": "setup_world_completeness", "display_name": "设定完整度",
         "axis": "world", "enabled": True},
    ]
    assert all(h["axis"] == "world" for h in hooks)
    assert not any(h["name"] == "setup_world_tension" for h in hooks)


def test_read_state_includes_both_review_hook_lists(monkeypatch):
    monkeypatch.setattr(cfg, "load_dialogue_prefs",
                        lambda: {"target_words": 3000,
                                 "disabled_buildtime_review_hooks": [], "disabled_runtime_review_hooks": []})
    monkeypatch.setattr(cfg, "_list_buildtime_review_hooks",
                        lambda: [{"name": "style", "display_name": "文风判官",
                                  "axis": "stage", "enabled": True}])
    monkeypatch.setattr(cfg, "_list_runtime_review_hooks",
                        lambda: [{"name": "fidelity", "display_name": "骨架保真判官", "enabled": True}])
    monkeypatch.setattr(cfg, "_list_setup_review_hooks",
                        lambda: [{"name": "setup_world_completeness", "display_name": "设定完整度",
                                  "axis": "world", "enabled": True}])
    state = cfg.read_state()
    assert state["buildtime_review_hooks"] == [
        {"name": "style", "display_name": "文风判官", "axis": "stage", "enabled": True},
    ]
    assert state["runtime_review_hooks"] == [
        {"name": "fidelity", "display_name": "骨架保真判官", "enabled": True},
    ]
    assert state["setup_review_hooks"] == [
        {"name": "setup_world_completeness", "display_name": "设定完整度",
         "axis": "world", "enabled": True},
    ]


def test_read_state_includes_setup_review_hooks(monkeypatch, tmp_path):
    from api.hub import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    client = TestClient(app)
    resp = client.get("/api/author-loop/dialogue-config")
    data = resp.json()
    names = {h["name"] for h in data["setup_review_hooks"]}
    assert "setup_world_completeness" in names
    assert all(h["axis"] == "world" for h in data["setup_review_hooks"])
    assert len(names) == 3


def test_dialogue_config_isolated_per_novel(monkeypatch, tmp_path):
    from api.hub import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    client = TestClient(app)

    put_a = client.put(
        "/api/author-loop/dialogue-config?novel_id=novel-a",
        json={"dialogue": {"target_words": 4000}},
    )
    assert put_a.status_code == 200

    get_b = client.get("/api/author-loop/dialogue-config?novel_id=novel-b")
    assert get_b.status_code == 200
    assert get_b.json()["config"]["target_words"] == 3000  # novel-b 未写过，仍是 schema 默认值

    get_a = client.get("/api/author-loop/dialogue-config?novel_id=novel-a")
    assert get_a.json()["config"]["target_words"] == 4000  # novel-a 的写入不影响 novel-b，也没丢


def test_put_dialogue_config_resets_setup_chat_when_chat_identity_changes(monkeypatch, tmp_path):
    """chat_identity 会在 build_agent() 建立单例时被烤成静态 prompt 字符串（见
    compose_system_prompt）；保存一个变化的覆写值必须让该小说的单例失效，否则已经打开的
    对话页会继续用旧身份，直到切小说/清空对话之类的操作顺带触发失效。"""
    import api.hub as hub_mod
    from api.services.message_hub import MessageHub
    from fastapi.testclient import TestClient

    hub = MessageHub()
    monkeypatch.setattr(hub_mod, "HUB", hub)

    reset_calls: list[str | None] = []

    async def fake_reset_setup_chat(novel_id=None):
        reset_calls.append(novel_id)

    monkeypatch.setattr(hub, "reset_setup_chat", fake_reset_setup_chat)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))

    client = TestClient(hub_mod.app)
    r = client.put(
        "/api/author-loop/dialogue-config?novel_id=novel-a",
        json={"dialogue": {"chat_identity": "新身份"}},
    )
    assert r.status_code == 200
    assert reset_calls == ["novel-a"]


def test_put_dialogue_config_skips_reset_when_chat_identity_unchanged(monkeypatch, tmp_path):
    """target_words 等无关字段的保存频繁发生（滑块拖动），不该每次都重建 agent 单例
    （丢弃 checkpointer 连接 + 重新计算 tool embedding 有实际开销）。"""
    import api.hub as hub_mod
    from api.services.message_hub import MessageHub
    from fastapi.testclient import TestClient

    hub = MessageHub()
    monkeypatch.setattr(hub_mod, "HUB", hub)

    reset_calls: list[str | None] = []

    async def fake_reset_setup_chat(novel_id=None):
        reset_calls.append(novel_id)

    monkeypatch.setattr(hub, "reset_setup_chat", fake_reset_setup_chat)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))

    client = TestClient(hub_mod.app)
    r = client.put(
        "/api/author-loop/dialogue-config?novel_id=novel-a",
        json={"dialogue": {"target_words": 4000}},
    )
    assert r.status_code == 200
    assert reset_calls == []


def test_put_dialogue_config_skips_reset_when_chat_identity_resaved_unchanged(monkeypatch, tmp_path):
    """保存的覆写值跟当前生效值字面相同（比如用户没改动就失焦）也不该重建单例。"""
    import api.hub as hub_mod
    from api.services.message_hub import MessageHub
    from fastapi.testclient import TestClient

    hub = MessageHub()
    monkeypatch.setattr(hub_mod, "HUB", hub)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))

    client = TestClient(hub_mod.app)
    client.put(
        "/api/author-loop/dialogue-config?novel_id=novel-a",
        json={"dialogue": {"chat_identity": "已有身份"}},
    )

    reset_calls: list[str | None] = []

    async def fake_reset_setup_chat(novel_id=None):
        reset_calls.append(novel_id)

    monkeypatch.setattr(hub, "reset_setup_chat", fake_reset_setup_chat)

    r = client.put(
        "/api/author-loop/dialogue-config?novel_id=novel-a",
        json={"dialogue": {"chat_identity": "已有身份"}},
    )
    assert r.status_code == 200
    assert reset_calls == []


def test_resolved_identity_delegates_to_agent_layer(monkeypatch):
    monkeypatch.setattr(
        "engine.setup_chat.agent.resolved_default_identity",
        lambda: "SENTINEL默认身份",
    )
    assert cfg._resolved_identity() == "SENTINEL默认身份"
