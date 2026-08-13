from engine.story_sandbox.prompt import KEEP_FULL_TURNS, build_sandbox_system_prompt


def _no_prose_style(monkeypatch):
    monkeypatch.setattr("engine.execution.prose_style.build_active_prose_style_card", lambda: "")


def _stub_cards(monkeypatch):
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_character_card",
        lambda name, chapter, stage, *, include_persona=True: f"角色：{name}（章{chapter}·幕{stage}）",
    )


def test_build_sandbox_system_prompt_opening_includes_world_and_cast(monkeypatch):
    _stub_cards(monkeypatch)
    monkeypatch.setattr(
        "engine.setup.chat_summary.render_world_chat", lambda wb: "一个测试世界",
    )
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    prompt, opening_names = build_sandbox_system_prompt(
        1, is_opening=True, character_states={"甲": {}},
    )
    assert "一个测试世界" in prompt
    assert "角色：甲（章1·幕1）" in prompt
    assert "开场设定" not in prompt  # anchor block removed entirely (2026-07-24)
    assert opening_names == {"甲"}


def test_build_sandbox_system_prompt_opening_empty_character_states_renders_no_cast_block(monkeypatch):
    _stub_cards(monkeypatch)
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    prompt, opening_names = build_sandbox_system_prompt(9, is_opening=True)
    assert "在场角色档案" not in prompt
    assert opening_names == set()


def test_build_sandbox_system_prompt_injects_prose_style(monkeypatch):
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card",
        lambda: "【SENTINEL文风卡内容】",
    )
    prompt, _ = build_sandbox_system_prompt(1, is_opening=True)
    assert "【SENTINEL文风卡内容】" in prompt


def test_build_sandbox_system_prompt_freeform_omits_world_and_cast(monkeypatch):
    calls = []

    def _fake_render_world_chat(wb):
        calls.append(wb)
        return "一个测试世界"

    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", _fake_render_world_chat)
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card",
        lambda: "【SENTINEL文风卡内容】",
    )
    prompt, opening_names = build_sandbox_system_prompt(
        1, is_opening=False, character_states={"甲": {}},
    )
    assert "一个测试世界" not in prompt
    assert "在场角色档案" not in prompt
    assert "【SENTINEL文风卡内容】" in prompt
    assert calls == []  # render_world_chat must not even be called on the freeform path
    assert opening_names == set()  # non-opening turns never exclude anything


def test_build_sandbox_system_prompt_free_mode_opening_has_no_core_xp(monkeypatch):
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    monkeypatch.setattr(
        "engine.setup.chat_summary.render_world_chat", lambda wb: "自由模式世界观",
    )
    prompt, _ = build_sandbox_system_prompt(0, is_opening=True)
    assert "自由模式世界观" in prompt
    assert "本章题材基调" not in prompt


def test_build_sandbox_system_prompt_chapter_mode_opening_has_core_xp(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    monkeypatch.setattr(
        "repositories.get_plot_repo",
        lambda: type("R", (), {"chapter_core_xp": staticmethod(lambda ch: ["复仇"])})(),
    )
    prompt, _ = build_sandbox_system_prompt(1, is_opening=True)
    assert "复仇" in prompt


def test_build_sandbox_system_prompt_free_mode_non_opening_reuses_freeform_framing(monkeypatch):
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    prompt, _ = build_sandbox_system_prompt(0, is_opening=False)
    assert "没有预设大纲" in prompt  # _FREEFORM_ROLE_FRAMING text, shared with chapter mode


def test_build_sandbox_system_prompt_opening_returns_names_that_got_a_cast_card(monkeypatch):
    _stub_cards(monkeypatch)
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    _prompt, opening_names = build_sandbox_system_prompt(
        1, is_opening=True, character_states={"甲": {}},
    )
    assert opening_names == {"甲"}


def test_build_sandbox_system_prompt_non_opening_returns_empty_opening_names(monkeypatch):
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    _prompt, opening_names = build_sandbox_system_prompt(1, is_opening=False)
    assert opening_names == set()  # must NOT still exclude opening names on later turns


def test_build_sandbox_system_prompt_progress_block_first_turn_has_no_history(monkeypatch):
    _no_prose_style(monkeypatch)
    prompt, _ = build_sandbox_system_prompt(1, is_opening=False)
    assert "暂无，这是第一段" in prompt
    assert "还没有历史" in prompt


def test_build_sandbox_system_prompt_progress_block_renders_arbitrary_state_fields_generically(
    monkeypatch,
):
    _no_prose_style(monkeypatch)
    prompt, _ = build_sandbox_system_prompt(
        1, is_opening=False,
        rolling_summary="甲乙已经吵完架。",
        turns=[{"instruction": "写甲的反应", "prose": "甲转身走了。"}],
        character_states={"甲": {"personality": "愤怒", "hobbies": ["炼药"]}},
    )
    assert "甲乙已经吵完架。" in prompt
    assert "写甲的反应" in prompt and "甲转身走了。" in prompt
    assert "personality：愤怒" in prompt
    assert "hobbies" in prompt  # list values render too, not just strings


def test_build_sandbox_system_prompt_progress_block_keeps_only_last_keep_full_turns_verbatim(
    monkeypatch,
):
    _no_prose_style(monkeypatch)
    turns = [{"instruction": f"第{i}轮", "prose": f"正文{i}"} for i in range(5)]
    prompt, _ = build_sandbox_system_prompt(1, is_opening=False, turns=turns)
    for i in range(5 - KEEP_FULL_TURNS):
        assert f"正文{i}" not in prompt
    for i in range(5 - KEEP_FULL_TURNS, 5):
        assert f"正文{i}" in prompt


def test_build_sandbox_system_prompt_progress_block_renders_scene_state_fields(monkeypatch):
    _no_prose_style(monkeypatch)
    prompt, _ = build_sandbox_system_prompt(
        1, is_opening=False,
        scene_state={"description": "昏暗的储物间", "objects": "纸箱散落一地"},
    )
    assert "description：昏暗的储物间" in prompt
    assert "objects：纸箱散落一地" in prompt


def test_build_sandbox_system_prompt_progress_block_empty_scene_state_shows_placeholder(monkeypatch):
    _no_prose_style(monkeypatch)
    prompt, _ = build_sandbox_system_prompt(1, is_opening=False)
    assert "暂无场景状态记录" in prompt


def test_build_sandbox_system_prompt_progress_block_renders_profile_overlay_fields(monkeypatch):
    _no_prose_style(monkeypatch)
    prompt, _ = build_sandbox_system_prompt(
        1, is_opening=False,
        character_profile={"甲": {"race": "精灵", "sliders": {"侵蚀度": {"level": 1, "text": "动摇"}}}},
    )
    assert "角色档案变更" in prompt
    assert "race：精灵" in prompt


def test_build_sandbox_system_prompt_progress_block_empty_profile_overlay_shows_placeholder(
    monkeypatch,
):
    _no_prose_style(monkeypatch)
    prompt, _ = build_sandbox_system_prompt(1, is_opening=False)
    assert "暂无变更" in prompt


def test_build_sandbox_system_prompt_progress_block_comes_after_prose_style(monkeypatch):
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "【SENTINEL文风卡内容】",
    )
    prompt, _ = build_sandbox_system_prompt(1, is_opening=False, rolling_summary="到目前的摘要")
    style_pos = prompt.index("【SENTINEL文风卡内容】")
    progress_pos = prompt.index("到目前的摘要")
    assert style_pos < progress_pos  # progress block trails every static block


def test_build_sandbox_system_prompt_progress_block_includes_dialogue_draft(monkeypatch):
    _no_prose_style(monkeypatch)
    prompt, _ = build_sandbox_system_prompt(
        1, is_opening=False, dialogue_draft="甲：（皱眉）你又来了。",
    )
    assert "本轮对话草稿" in prompt
    assert "甲：（皱眉）你又来了。" in prompt


def test_build_sandbox_system_prompt_progress_block_omits_dialogue_draft_when_empty(monkeypatch):
    _no_prose_style(monkeypatch)
    prompt, _ = build_sandbox_system_prompt(1, is_opening=False)
    assert "本轮对话草稿" not in prompt


def test_build_sandbox_system_prompt_free_mode_opening_renders_known_roster_fallback(monkeypatch):
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    prompt, _ = build_sandbox_system_prompt(
        0, is_opening=True, known_roster_fallback=["甲", "乙"],
    )
    assert "已知角色名单" in prompt
    assert "甲" in prompt and "乙" in prompt


def test_build_sandbox_system_prompt_free_mode_opening_omits_known_roster_fallback_when_empty(
    monkeypatch,
):
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    prompt, _ = build_sandbox_system_prompt(0, is_opening=True)
    assert "已知角色名单" not in prompt


def test_build_sandbox_system_prompt_chapter_mode_opening_also_renders_known_roster_fallback(
    monkeypatch,
):
    """Behavior change: chapter mode's opening turn now shares the exact same
    known_roster_fallback guardrail as free mode -- it's no longer free-mode-only."""
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    prompt, _ = build_sandbox_system_prompt(
        1, is_opening=True, known_roster_fallback=["甲", "乙"],
    )
    assert "已知角色名单" in prompt
    assert "甲" in prompt and "乙" in prompt


def test_build_sandbox_system_prompt_opening_renders_instruction_grounding_blocks(monkeypatch):
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    prompt, _ = build_sandbox_system_prompt(
        0, is_opening=True, known_roster_fallback=["甲", "乙", "丙"],
        instruction_grounding_graph="## 角色关系\n- 甲→乙",
        instruction_grounding_briefs=(
            "\n\n## 关联角色简卡（指令相关，仅供背景/关系参考——禁止让他们说话、登场或采取任何行动）\n"
            "【甲】简卡\n【乙】简卡"
        ),
    )
    assert "已知角色名单" in prompt
    assert "角色关系" in prompt
    assert "关联角色简卡" in prompt
    assert "【甲】简卡" in prompt


def test_build_sandbox_system_prompt_free_mode_opening_renders_known_locations(monkeypatch):
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    monkeypatch.setattr(
        "engine.setup.chat_summary.geography_names", lambda wb: ["废弃车站", "青云观"],
    )
    prompt, _ = build_sandbox_system_prompt(0, is_opening=True)
    assert "已知地点" in prompt
    assert "废弃车站" in prompt and "青云观" in prompt


def test_build_sandbox_system_prompt_free_mode_opening_omits_known_locations_when_empty(
    monkeypatch,
):
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    monkeypatch.setattr("engine.setup.chat_summary.geography_names", lambda wb: [])
    prompt, _ = build_sandbox_system_prompt(0, is_opening=True)
    assert "已知地点" not in prompt


def test_build_sandbox_system_prompt_chapter_mode_opening_never_renders_known_locations(
    monkeypatch,
):
    """Behavior: unlike known_roster_fallback (shared across both modes), the known-locations
    guardrail is free-mode only -- chapter mode omits it even when geography_names is non-empty."""
    monkeypatch.setattr(
        "engine.execution.prose_style.build_active_prose_style_card", lambda: "",
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    monkeypatch.setattr(
        "engine.setup.chat_summary.geography_names", lambda wb: ["废弃车站", "青云观"],
    )
    prompt, _ = build_sandbox_system_prompt(1, is_opening=True)
    assert "已知地点" not in prompt
