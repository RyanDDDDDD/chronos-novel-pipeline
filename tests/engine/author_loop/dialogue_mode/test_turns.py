"""回合渲染层:system 契约要素、整 stage 任务包组装。"""
from engine.author_loop.dialogue_mode.turns import (
    _fragment_beat_text,
    build_system_prompt,
    render_task_packet,
)


def test_system_prompt_contract_essentials():
    sys = build_system_prompt("【文风】怎么糙怎么写")
    assert "主笔扩写师" in sys
    assert "参考蓝本" in sys and "重写" in sys
    assert "终点" not in sys
    assert "整个 stage" in sys or "整 stage" in sys
    assert "文风调色档" in sys and "怎么糙怎么写" in sys
    assert "update_states" not in sys and "观察报告" not in sys
    assert "示例" not in sys


def test_system_prompt_forbids_verbatim_skeleton_reuse():
    # In real runs, the author output had ~62–66% character overlap with skeleton/dialogue
    # design (normalized diff). The old contract only forbade dropping facts, not verbatim
    # reuse, and the model misread "cannot be replaced" as "cannot change a single word".
    # Assert against the new skeleton-specific phrasing to avoid matching the existing
    # "dialogue writing" clause that only targets sample line copying.
    sys = build_system_prompt("")
    assert "骨架原句" in sys and "誊抄" in sys


def test_fragment_beat_text_breaks_after_sentence_end_punctuation():
    text = "甲踏进门槛，环视四周。乙背对着他站在窗边一动不动！这地方怎么回事？"
    fragmented = _fragment_beat_text(text)
    assert fragmented.split("\n") == [
        "甲踏进门槛，环视四周。",
        "乙背对着他站在窗边一动不动！",
        "这地方怎么回事？",
    ]


def test_fragment_beat_text_keeps_punctuation_itself_unchanged():
    # Only inserts \n after 。！？ -- must not strip/replace the punctuation characters.
    text = "他愣住了。"
    assert _fragment_beat_text(text) == "他愣住了。"


def test_task_packet_renders_beat_text_fragmented_by_sentence(monkeypatch):
    import engine.author_loop.dialogue_mode.turns as t
    monkeypatch.setattr(t, "render_character_card", lambda n, c, s, **kw: f"[{n}的卡]")
    stage = {
        "index": 0, "chapter": 1, "stage": 1, "characters": ["甲"],
        "beats": [{"beat_intent": "甲环视四周。乙一动不动！", "characters": ["甲"],
                   "chapter": 1, "stage": 1}],
    }
    packet = render_task_packet(stage=stage)
    assert "甲环视四周。\n乙一动不动！" in packet


def test_task_packet_lists_beats_as_subsections(monkeypatch):
    import engine.author_loop.dialogue_mode.turns as t
    monkeypatch.setattr(t, "render_character_card",
                        lambda n, c, s, **kw: f"[{n}的卡]")
    stage = {
        "index": 2, "chapter": 1, "stage": 2, "characters": ["甲", "乙"],
        "beats": [
            {"beat_intent": "甲缠住乙脚踝，低声安抚：「别怕。」", "characters": ["甲", "乙"],
             "chapter": 1, "stage": 2},
            {"beat_intent": "乙挣扎", "characters": ["甲", "乙"], "chapter": 1, "stage": 2},
        ],
    }
    packet = render_task_packet(stage=stage)
    assert "第 3 个 stage" in packet
    assert "第 1 拍" in packet and "甲缠住乙脚踝" in packet
    assert "第 2 拍" in packet and "乙挣扎" in packet
    assert "[甲的卡]" in packet and "[乙的卡]" in packet


def test_task_packet_puts_character_cards_before_skeleton(monkeypatch):
    # Character cards (incl. physique/psychology/clothing grounding) were appended at the
    # end of the user prompt, after the full stage skeleton + dialogue design. The author
    # reads left-to-right, so grounding should come first, before the beats that need it.
    import engine.author_loop.dialogue_mode.turns as t
    monkeypatch.setattr(t, "render_character_card",
                        lambda n, c, s, **kw: f"[{n}的卡]")
    stage = {
        "index": 0, "chapter": 1, "stage": 1, "characters": ["甲"],
        "beats": [{"beat_intent": "开场", "characters": ["甲"], "chapter": 1, "stage": 1}],
    }
    packet = render_task_packet(stage=stage)
    assert packet.index("[甲的卡]") < packet.index("本 stage 骨架")


def test_task_packet_renders_sensation_notes_block(monkeypatch):
    import engine.author_loop.dialogue_mode.turns as t
    monkeypatch.setattr(t, "render_character_card",
                        lambda n, c, s, **kw: f"[{n}的卡]")
    stage = {
        "index": 0, "chapter": 1, "stage": 1, "characters": ["甲"],
        "beats": [{"beat_intent": "甲前戏", "characters": ["甲"], "chapter": 1, "stage": 1,
                   "sensation_notes": ["小腹一阵酥麻"]}],
    }
    packet = render_task_packet(stage=stage)
    assert "本拍体感参考" in packet
    assert "小腹一阵酥麻" in packet


def test_task_packet_omits_sensation_block_when_absent(monkeypatch):
    import engine.author_loop.dialogue_mode.turns as t
    monkeypatch.setattr(t, "render_character_card", lambda n, c, s, **kw: "卡")
    stage = {
        "index": 0, "chapter": 1, "stage": 1, "characters": ["甲"],
        "beats": [{"beat_intent": "开场", "characters": ["甲"], "chapter": 1, "stage": 1,
                   "sensation_notes": []}],
    }
    packet = render_task_packet(stage=stage)
    assert "体感参考" not in packet


def test_task_packet_renders_dialogue_draft_block(monkeypatch):
    import engine.author_loop.dialogue_mode.turns as t
    monkeypatch.setattr(t, "render_character_card", lambda n, c, s, **kw: f"[{n}的卡]")
    stage = {
        "index": 0, "chapter": 1, "stage": 1, "characters": ["甲"],
        "beats": [{"beat_intent": "甲开口", "characters": ["甲"], "chapter": 1, "stage": 1,
                   "dialogue_draft": "甲（意图：试探；动作/心理：皱眉）：你在做什么。"}],
    }
    packet = render_task_packet(stage=stage)
    assert "本拍台词草稿" in packet
    assert "必须缝合进这一拍正文" in packet
    assert "甲（意图：试探；动作/心理：皱眉）：你在做什么。" in packet


def test_task_packet_omits_dialogue_draft_block_when_absent(monkeypatch):
    import engine.author_loop.dialogue_mode.turns as t
    monkeypatch.setattr(t, "render_character_card", lambda n, c, s, **kw: "卡")
    stage = {
        "index": 0, "chapter": 1, "stage": 1, "characters": ["甲"],
        "beats": [{"beat_intent": "开场", "characters": ["甲"], "chapter": 1, "stage": 1,
                   "dialogue_draft": ""}],
    }
    packet = render_task_packet(stage=stage)
    assert "本拍台词草稿" not in packet


def test_task_packet_passes_character_states_into_cards(monkeypatch):
    import engine.author_loop.dialogue_mode.turns as turns_mod

    captured = {}

    def fake_render_card(name, chapter, stage, *, include_persona=True, dynamic_state=None):
        captured[name] = dynamic_state
        return f"角色：{name}"
    monkeypatch.setattr(turns_mod, "render_character_card", fake_render_card)

    stage = {
        "chapter": 1, "stage": 1, "index": 0, "characters": ["甲"],
        "beats": [{"beat_intent": "拍一。"}],
    }
    render_task_packet(
        stage=stage,
        character_states={"甲": {"psychology": "紧张"}},
    )
    assert captured["甲"] == {"psychology": "紧张"}


def test_task_packet_passes_none_when_character_has_no_state(monkeypatch):
    import engine.author_loop.dialogue_mode.turns as turns_mod

    captured = {}

    def fake_render_card(name, chapter, stage, *, include_persona=True, dynamic_state=None):
        captured[name] = dynamic_state
        return f"角色：{name}"
    monkeypatch.setattr(turns_mod, "render_character_card", fake_render_card)

    stage = {
        "chapter": 1, "stage": 1, "index": 0, "characters": ["乙"],
        "beats": [{"beat_intent": "拍一。"}],
    }
    render_task_packet(stage=stage, character_states={"甲": {"psychology": "紧张"}})
    assert captured["乙"] is None


def test_render_task_packet_includes_recall_context_when_present():
    stage = {"index": 0, "chapter": 1, "stage": 1, "characters": [], "beats": []}
    out = render_task_packet(stage=stage, recall_context="## 相关历史/设定回收\n- 第2章：旧账未清")
    assert "相关历史/设定回收" in out
    assert "旧账未清" in out


def test_render_task_packet_omits_recall_section_when_empty():
    stage = {"index": 0, "chapter": 1, "stage": 1, "characters": [], "beats": []}
    out = render_task_packet(stage=stage, recall_context="")
    assert "相关历史/设定回收" not in out

