from engine.author_loop.dialogue_mode.chapter_state import render_state_view, resolve_card_state


def test_resolve_card_state_reads_clothing_and_state_directly_from_archive(monkeypatch):
    """clothing/state 不再靠 micro seed,直接从本章 archive 按坐标折叠。"""
    import engine.author_loop.dialogue_mode.chapter_state as cs
    from repositories.entities import Character

    lore_char = Character(name="甲", state={"psychology": "平静"})
    monkeypatch.setattr(cs, "_lore_repo", lambda: type("I", (), {
        "get_character": lambda _s, n: lore_char if n == "甲" else None,
    })())
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.character_timeline.deltas_upto",
        lambda _n, c, s: [{
            "chapter": c, "stage": s,
            "delta": {"clothing": "作战服", "state": {"psychology": "动摇", "physiology": "紧绷"}},
        }],
    )
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.collect_merge_strategies", lambda: {},
    )
    out = resolve_card_state("甲", 1, 1)
    assert out["clothing"] == "作战服"
    assert out["state"]["psychology"] == "动摇"
    assert out["state"]["physiology"] == "紧绷"


def test_resolve_card_state_clothing_tracks_scene_change_across_stages(monkeypatch):
    """室内→海边这类场景切换:后一 stage 的 archive clothing 必须覆盖前一 stage(本次修复的核心回归)。"""
    import engine.author_loop.dialogue_mode.chapter_state as cs
    from repositories.entities import Character

    lore_char = Character(name="甲")
    monkeypatch.setattr(cs, "_lore_repo", lambda: type("I", (), {
        "get_character": lambda _s, n: lore_char if n == "甲" else None,
    })())

    def _deltas_upto(_n, c, s):
        all_snaps = [
            {"chapter": 1, "stage": 1, "delta": {"clothing": "室内便装"}},
            {"chapter": 1, "stage": 2, "delta": {"clothing": "海边泳装"}},
        ]
        return [sn for sn in all_snaps if (sn["chapter"], sn["stage"]) <= (c, s)]

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.character_timeline.deltas_upto",
        _deltas_upto,
    )
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.collect_merge_strategies", lambda: {},
    )
    assert resolve_card_state("甲", 1, 1)["clothing"] == "室内便装"
    assert resolve_card_state("甲", 1, 2)["clothing"] == "海边泳装"


def test_resolve_card_state_includes_chapter_macro_from_timeline(monkeypatch):
    """人格/自称等宏观字段跟 clothing/state 一样,都从本章 archive 折进卡面(同一条读取路径)。"""
    import engine.author_loop.dialogue_mode.chapter_state as cs
    from repositories.entities import Character

    lore_char = Character(name="乙", role="学生")
    monkeypatch.setattr(cs, "_lore_repo", lambda: type("I", (), {
        "get_character": lambda _s, n: lore_char if n == "乙" else None,
    })())
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.character_timeline.deltas_upto",
        lambda _n, c, s: [{
            "chapter": c, "stage": s,
            "delta": {
                "archetype": "内向退缩型",
                "self_ref": {"_default": ["柚子"]},
                "state": {"psychology": "旧心理"},
            },
        }],
    )
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.collect_merge_strategies", lambda: {},
    )
    out = resolve_card_state("乙", 2, 1)
    assert out.get("archetype") == "内向退缩型"
    assert out.get("self_ref") == {"_default": ["柚子"]}
    assert out["state"]["psychology"] == "旧心理"


def test_resolve_card_state_includes_chapter_macro_verbal_tic(monkeypatch):
    """口癖是宏观 timeline 字段,跟 archetype/self_ref 一样能从本章 delta 折进卡面。"""
    import engine.author_loop.dialogue_mode.chapter_state as cs
    from repositories.entities import Character

    lore_char = Character(name="乙", role="学生")
    monkeypatch.setattr(cs, "_lore_repo", lambda: type("I", (), {
        "get_character": lambda _s, n: lore_char if n == "乙" else None,
    })())
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.character_timeline.deltas_upto",
        lambda _n, c, s: [{
            "chapter": c, "stage": s,
            "delta": {"verbal_tic": "句尾爱加「呢」", "state": {"psychology": "旧心理"}},
        }],
    )
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.collect_merge_strategies", lambda: {},
    )
    out = resolve_card_state("乙", 2, 1)
    assert out.get("verbal_tic") == "句尾爱加「呢」"


def test_resolve_card_state_seeds_verbal_tic_from_lore_with_no_timeline_delta(monkeypatch):
    """核心回归:verbal_tic 创建期种子值靠 resolve_from 的 lore-baseline 折叠自动传导,
    零 timeline delta 也能读到。"""
    import engine.author_loop.dialogue_mode.chapter_state as cs
    from repositories.entities import Character

    lore_char = Character(
        name="乙", role="学生",
        verbal_tic="句尾爱加「呢」，紧张时会重复最后两个字",
    )
    monkeypatch.setattr(cs, "_lore_repo", lambda: type("I", (), {
        "get_character": lambda _s, n: lore_char if n == "乙" else None,
    })())
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.character_timeline.deltas_upto",
        lambda _n, _c, _s: [],
    )
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.collect_merge_strategies", lambda: {},
    )
    out = resolve_card_state("乙", 1, 1)
    assert out.get("verbal_tic") == "句尾爱加「呢」，紧张时会重复最后两个字"


def test_render_state_view_renders_five_fields():
    dynamic_state = {
        "psychology": "戒备", "posture": "微屈膝", "clothing": "校服",
        "action": "攥紧衣角", "demeanor": "低头",
    }
    out = render_state_view(dynamic_state)
    assert "心理：戒备" in out
    assert "体态：微屈膝" in out
    assert "着装：校服" in out
    assert "动作：攥紧衣角" in out
    assert "神态：低头" in out


def test_render_state_view_shows_placeholder_for_missing_fields():
    out = render_state_view({"psychology": "戒备"})
    assert "体态：（未设定）" in out
