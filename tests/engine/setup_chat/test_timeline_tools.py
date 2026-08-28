import engine.setup_chat.tools as t
import pytest
from repo_test_helpers import seed_lore, seed_plot


@pytest.fixture(autouse=True)
def _rebuild_character_tool_schemas(monkeypatch):
    """Overrides the conftest fixture of the same name: this file's fixtures use
    武器/流派/身份 instead of a real content pack's mature-content fields, so custom_fields()
    must be patched before add_character/edit_character's args_schema is rebuilt from it."""
    import context.content_packs as cp
    from engine.setup_chat.tool_args import build_add_character_args, build_edit_character_args

    monkeypatch.setattr(
        cp,
        "custom_fields",
        lambda: [
            cp.CustomFieldSpec(name="武器", required=True, timeline_delta=True),
            cp.CustomFieldSpec(name="流派", required=True, timeline_delta=True),
            cp.CustomFieldSpec(name="身份", required=True, timeline_delta=True),
        ],
    )
    t.add_character.args_schema = build_add_character_args()
    t.edit_character.args_schema = build_edit_character_args()

_DEFAULT_LORE = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
                  "causal_anchors": {}, "sliders": {"侵蚀度": 0}}]
_DEFAULT_PLOT = [
    {"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "title": "s", "location": "屋内", "description": "甲登场",
         "clothing": {"甲": "校服"}},
        {"stage_num": 2, "title": "s2", "location": "屋外", "description": "甲续场",
         "clothing": {"甲": "校服"}},
    ]},
    {"chapter": 2, "title": "二", "core_xp": [], "stages": [
        {"stage_num": 1, "title": "s", "location": "屋外", "description": "甲续场",
         "clothing": {"甲": "校服"}},
    ]},
]
_TWO_CHAPTER_PLOT = _DEFAULT_PLOT


def _stub_scan(monkeypatch, names: tuple[str, ...] = ("甲", "乙")) -> None:
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [n for n in names if n in text],
    )


def _seed_context(
    monkeypatch,
    tmp_path,
    *,
    lore: list[dict] | None = None,
    plot: list[dict] | None = None,
    scan_names: tuple[str, ...] = ("甲", "乙"),
) -> None:
    del tmp_path
    seed_lore(lore if lore is not None else _DEFAULT_LORE)
    seed_plot(plot if plot is not None else _DEFAULT_PLOT)
    _stub_scan(monkeypatch, scan_names)


def _patch(monkeypatch, tmp_path, *, lore=None, plot=None):
    _seed_context(monkeypatch, tmp_path, lore=lore, plot=plot)
    captured: dict = {}
    monkeypatch.setattr(t, "_persist_archive",
                        lambda name, ch, arch: captured.update(archive=arch))
    return captured


@pytest.mark.asyncio
async def test_write_persists_delta_and_resolves(monkeypatch, tmp_path):
    captured = _patch(monkeypatch, tmp_path)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {
            "self_ref": {"_default": ["爱丽丝"]},
            "sliders": {"侵蚀度": {"level": 1, "text": "动摇"}},
        },
    })
    assert "甲" in out and "爱丽丝" in out
    from context import character_timeline
    snaps = character_timeline.load_timeline("甲")["snapshots"]
    assert snaps and snaps[-1]["delta"]["self_ref"] == {"_default": ["爱丽丝"]}
    assert snaps[-1]["stage"] == 1
    assert len(snaps) == 1
    #The complete file output by resolve is cached
    assert captured["archive"]["self_ref"] == {"_default": ["爱丽丝"]}
    arch = captured["archive"]
    assert arch["name"] == "甲" and arch["role"] == "同质堕落型"


@pytest.mark.asyncio
async def test_write_unchanged_field_inherited(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"self_ref": {"_default": ["爱丽丝"]}},
    })
    #chapter2 不写 self_ref → resolve 应沿用 chapter1 的
    out = await t.write_character_archive.ainvoke({
        "chapter": 2, "name": "甲",
        "profile": {"sliders": {"侵蚀度": {"level": 1, "text": "动摇"}}},
    })
    assert "爱丽丝" in out


@pytest.mark.asyncio
async def test_timeline_status_lists_roster_and_built(monkeypatch, tmp_path):
    plot = [{"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "location": "屋内", "description": "甲乙登场"}]}]
    _seed_context(monkeypatch, tmp_path, plot=plot)
    from context import character_timeline
    character_timeline.append_stage("甲", 1, 1, {"sliders": {"侵蚀度": {"level": 1, "text": "动摇"}}})

    out = await t.read_archive_status.ainvoke({"chapter": 1})
    assert "甲" in out and "乙" in out
    assert "已推" in out and "待推" in out


@pytest.mark.asyncio
async def test_read_seed_renders_context(monkeypatch, tmp_path):
    plot = [{"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "location": "屋内", "description": "甲登场"}]}]
    _seed_context(monkeypatch, tmp_path, plot=plot)
    out = await t.read_archive_seed.ainvoke({"chapter": 1, "name": "甲"})
    assert "甲" in out and ("cold_start" in out or "首次" in out)
    assert "{" not in out  #Literalize, don't spit out raw JSON


def test_normalize_delta_strips_unknown_and_validates_slider_shape():
    import engine.setup_chat.tools as t
    delta = {
        "场景标题": "日常伪装期",
        "thought_process": {"delta": "d"},
        "gender": "xeno",
        "self_ref": "我",
        "sliders": {"同化进度": {"level": 2, "text": "人格已彻底翻转，改造显现"}},
        "state": {"psychology": "x"},
    }
    out, dropped = t._normalize_delta(delta)
    assert set(dropped) == {"场景标题", "thought_process", "state"}
    assert "场景标题" not in out and "thought_process" not in out
    assert out["gender"] == "xeno"
    assert out["self_ref"] == {"_default": ["我"]}
    assert out["sliders"] == {"同化进度": {"level": 2, "text": "人格已彻底翻转，改造显现"}}
    assert "state" not in out


def test_normalize_delta_drops_slider_legacy_string_shape():
    import engine.setup_chat.tools as t
    delta = {"sliders": {"同化进度": "旧形态裸字符串"}, "state": {"psychology": "x"}}
    out, dropped = t._normalize_delta(delta)
    assert "sliders" in dropped
    assert "sliders" not in out


def test_normalize_delta_drops_slider_missing_level_or_text():
    import engine.setup_chat.tools as t
    delta = {"sliders": {"同化进度": {"text": "没给档位号"}}, "state": {"psychology": "x"}}
    out, dropped = t._normalize_delta(delta)
    assert "sliders" in dropped
    assert "sliders" not in out


def test_persist_archive_writes_file(monkeypatch, tmp_path):
    """_persist_archive must persist via ArchiveRepository (SQLite-backed)."""
    _seed_context(monkeypatch, tmp_path)
    import repositories

    t._persist_archive("甲", 1, {"name": "甲", "role": "r", "stages": {"1": {}}})
    arch = repositories.get_archive_repo().get("甲", 1)
    assert arch is not None
    assert arch.name == "甲"


@pytest.mark.asyncio
async def test_write_rejects_empty_personality(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"personality": "   "}})
    assert "personality" in out and "未写入" in out
    from context import character_timeline
    assert not [s for s in character_timeline.load_timeline("甲")["snapshots"] if s["chapter"] == 1]


@pytest.mark.asyncio
async def test_write_accepts_freeform_personality(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"personality": "外冷内热，嘴硬但会偷看对方反应"}})
    assert "未写入" not in out
    from context import character_timeline
    snaps = character_timeline.load_timeline("甲")["snapshots"]
    assert snaps[-1]["delta"]["personality"] == "外冷内热，嘴硬但会偷看对方反应"


@pytest.mark.asyncio
async def test_write_drops_legacy_archetype_key(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"archetype": "沉稳内敛型", "verbal_tic": "习惯性沉默"}})
    assert "未写入" not in out
    from context import character_timeline
    snaps = character_timeline.load_timeline("甲")["snapshots"]
    assert "archetype" not in snaps[-1]["delta"]
    assert "personality" not in snaps[-1]["delta"]
    assert snaps[-1]["delta"]["verbal_tic"] == "习惯性沉默"


@pytest.mark.asyncio
async def test_write_accepts_freeform_physique(monkeypatch, tmp_path):
    """
physique changed to free-form: Chinese/any subfield keys will not be rejected (no fixed slot verification)."""
    _patch(monkeypatch, tmp_path)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"physique": {"面容": "冷峻", "手臂": "有伤疤"}}})
    assert "未写入" not in out
    from context import character_timeline
    snaps = character_timeline.load_timeline("甲")["snapshots"]
    assert snaps[-1]["delta"]["physique"] == {"面容": "冷峻", "手臂": "有伤疤"}


@pytest.mark.asyncio
async def test_write_rejects_out_of_range_level(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "engine.archive.sliders.character_rubrics",
        lambda name: {"侵蚀度": {"0": "清醒", "1": "动摇"}} if name == "甲" else {},
    )
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"sliders": {"侵蚀度": {"level": 5, "text": "越界"}}}})
    assert "档位" in out and "5" in out
    from context import character_timeline
    assert not [s for s in character_timeline.load_timeline("甲")["snapshots"] if s["chapter"] == 1]


@pytest.mark.asyncio
async def test_write_rolls_back_new_stage_on_archive_validation_failure(monkeypatch, tmp_path):
    """Regression: assert_valid runs AFTER character_timeline.append_stage (resolve needs the
    delta already committed to fold it in) -- a rejection there must not leave the timeline
    holding a delta whose archive was never persisted, or missing_timeline_targets() would
    permanently consider this (chapter, name) already built (its check is timeline-presence-
    only) and "一键构建" would report nothing missing forever, with archive.json never written."""
    captured = _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(t, "assert_valid", lambda archive: (_ for _ in ()).throw(ValueError("boom")))

    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"self_ref": {"_default": ["爱丽丝"]}},
    })
    assert "档案校验未通过" in out
    assert "archive" not in captured  # _persist_archive never ran

    from context import character_timeline
    assert not [s for s in character_timeline.load_timeline("甲")["snapshots"] if s["chapter"] == 1]


@pytest.mark.asyncio
async def test_write_restores_previous_stage_on_archive_validation_failure(monkeypatch, tmp_path):
    """Companion to the rollback test above: if a coordinate already held a GOOD prior delta
    (from an earlier successful write) and a later re-write to that same coordinate fails
    validation, the rollback must restore the previous delta, not just wipe the coordinate --
    otherwise a working chapter would be silently blanked by a failed edit attempt."""
    _patch(monkeypatch, tmp_path)
    ok = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"self_ref": {"_default": ["爱丽丝"]}},
    })
    assert "档案校验未通过" not in ok

    monkeypatch.setattr(t, "assert_valid", lambda archive: (_ for _ in ()).throw(ValueError("boom")))
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"self_ref": {"_default": ["贝拉"]}},
    })
    assert "档案校验未通过" in out

    from context import character_timeline
    snaps = [s for s in character_timeline.load_timeline("甲")["snapshots"] if s["chapter"] == 1]
    assert len(snaps) == 1
    assert snaps[0]["delta"]["self_ref"] == {"_default": ["爱丽丝"]}  # restored, not the rejected 贝拉


@pytest.mark.asyncio
async def test_write_accepts_personality_change_without_level_change(monkeypatch, tmp_path):
    """personality_gate_violations retired (archetype-era guardrail, archetype itself is gone) --
    a personality change with no accompanying slider-level change is no longer rejected."""
    _patch(monkeypatch, tmp_path)
    await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"personality": "外冷内热",
                    "sliders": {"侵蚀度": {"level": 1, "text": "动摇"}}}})
    out = await t.write_character_archive.ainvoke({
        "chapter": 2, "name": "甲",
        "profile": {"personality": "彻底服从",
                    "sliders": {"侵蚀度": {"level": 1, "text": "还是动摇"}}}})
    assert "档位" not in out
    from context import character_timeline
    assert [s for s in character_timeline.load_timeline("甲")["snapshots"] if s["chapter"] == 2]


@pytest.mark.asyncio
async def test_write_persists_verbal_tic(monkeypatch, tmp_path):
    """口癖走跟 personality 一样的宏观 timeline delta 机制：写入后能在 resolve 出的 archive 里读到。"""
    captured = _patch(monkeypatch, tmp_path)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {
            "verbal_tic": "句尾爱加「呢」，紧张时会重复最后两个字",
        },
    })
    assert "未写入" not in out
    assert captured["archive"]["verbal_tic"] == "句尾爱加「呢」，紧张时会重复最后两个字"


def test_normalize_delta_keeps_verbal_tic():
    delta = {"verbal_tic": "句尾爱加「呢」", "state": {"psychology": "x"}}
    out, dropped = t._normalize_delta(delta)
    assert "verbal_tic" not in dropped
    assert out["verbal_tic"] == "句尾爱加「呢」"
    assert "state" in dropped


def test_normalize_delta_keeps_hobbies_list():
    out, dropped = t._normalize_delta({"hobbies": ["爱吃甜食", "  ", "喜欢刺绣"]})
    assert "hobbies" not in dropped
    assert out["hobbies"] == ["爱吃甜食", "喜欢刺绣"]


def test_normalize_delta_drops_non_list_hobbies():
    out, dropped = t._normalize_delta({"hobbies": "爱吃甜食"})
    assert out == {}
    assert dropped == ["hobbies"]


@pytest.mark.asyncio
async def test_write_persists_hobbies(monkeypatch, tmp_path):
    captured = _patch(monkeypatch, tmp_path)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"hobbies": ["爱吃甜食", "喜欢刺绣"]},
    })
    assert "未写入" not in out
    assert captured["archive"]["hobbies"] == ["爱吃甜食", "喜欢刺绣"]


@pytest.mark.asyncio
async def test_write_hobbies_unchanged_is_inherited(monkeypatch, tmp_path):
    captured = _patch(monkeypatch, tmp_path)
    await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"hobbies": ["爱吃甜食"]},
    })
    await t.write_character_archive.ainvoke({
        "chapter": 2, "name": "甲",
        "profile": {"sliders": {"侵蚀度": {"level": 1, "text": "动摇"}}},
    })
    assert captured["archive"]["hobbies"] == ["爱吃甜食"]


@pytest.mark.asyncio
async def test_write_hobbies_overrides_lore_baseline(monkeypatch, tmp_path):
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
             "causal_anchors": {}, "sliders": {"侵蚀度": 0},
             "hobbies": ["旧爱好"]}]
    captured = _patch(monkeypatch, tmp_path, lore=lore)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"hobbies": ["新爱好"]},
    })
    assert "未写入" not in out
    assert captured["archive"]["hobbies"] == ["新爱好"]


@pytest.mark.asyncio
async def test_read_seed_shows_prior_hobbies_rolling(monkeypatch, tmp_path):
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
             "causal_anchors": {}, "sliders": {"侵蚀度": 0},
             "hobbies": ["旧爱好"]}]
    _patch(monkeypatch, tmp_path, lore=lore, plot=_TWO_CHAPTER_PLOT)
    await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"hobbies": ["新爱好"]},
    })
    out = await t.read_archive_seed.ainvoke({"chapter": 2, "name": "甲"})
    assert "前序爱好：新爱好" in out
    assert "旧爱好" not in out


@pytest.mark.asyncio
async def test_write_verbal_tic_unchanged_is_inherited(monkeypatch, tmp_path):
    """跟 personality 同语义：某章没给 verbal_tic → resolve 时沿用前值，不会被清空。"""
    _patch(monkeypatch, tmp_path)
    await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲", "profile": {
            "verbal_tic": "句尾爱加「呢」",
        }})
    out = await t.write_character_archive.ainvoke({
        "chapter": 2, "name": "甲", "profile": {
            "sliders": {"侵蚀度": {"level": 1, "text": "动摇"}},
        }})
    assert "句尾爱加「呢」" in out


@pytest.mark.asyncio
async def test_read_seed_shows_identity_background_and_hobbies_cold_start(monkeypatch, tmp_path):
    """身份背景/爱好是静态 lore 字段，cold_start（无前序 delta）也照样展示。"""
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
             "causal_anchors": {}, "sliders": {"侵蚀度": 0},
             "identity_background": "没落贵族之女，寄人篱下",
             "hobbies": ["爱吃甜食", "喜欢刺绣"]}]
    _seed_context(monkeypatch, tmp_path, lore=lore)

    out = await t.read_archive_seed.ainvoke({"chapter": 1, "name": "甲"})
    assert "身份背景：没落贵族之女，寄人篱下" in out
    assert "爱好：爱吃甜食、喜欢刺绣" in out


@pytest.mark.asyncio
async def test_read_seed_shows_sliders_cold_start(monkeypatch, tmp_path):
    """cold_start（角色首次出场，无前序 delta）须能读到 lore 里 sliders 的档位号+描述，
    agent 才有登场起点可依据推演，而不是凭空猜。"""
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型", "causal_anchors": {},
             "sliders": {"侵蚀度": {"level": 1, "text": "已有轻微裂痕"}}}]
    _seed_context(monkeypatch, tmp_path, lore=lore)

    out = await t.read_archive_seed.ainvoke({"chapter": 1, "name": "甲"})
    assert "登场初始滑块" in out
    assert "侵蚀度：档位1·已有轻微裂痕" in out


@pytest.mark.asyncio
async def test_read_seed_shows_prior_verbal_tic_rolling(monkeypatch, tmp_path):
    """rolling 模式（第2章读，第1章已推过 delta）要能看到前序口癖，供 agent 判断沿用还是改写。"""
    _seed_context(monkeypatch, tmp_path, plot=_TWO_CHAPTER_PLOT)
    from context import character_timeline
    character_timeline.append_stage("甲", 1, 1, {"verbal_tic": "句尾爱加「呢」"})

    out = await t.read_archive_seed.ainvoke({"chapter": 2, "name": "甲"})
    assert "rolling" in out or "滚动" in out
    assert "前序口癖：句尾爱加「呢」" in out


@pytest.mark.asyncio
async def test_read_seed_shows_initial_verbal_tic_cold_start(monkeypatch, tmp_path):
    """口癖创建期若已声明种子值，cold_start（首章、无前序 delta）也要能看到，供 agent 决定沿用/改写。"""
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
             "causal_anchors": {}, "sliders": {"侵蚀度": 0},
             "verbal_tic": "句尾爱加「呢」，紧张时会重复最后两个字"}]
    _seed_context(monkeypatch, tmp_path, lore=lore)

    out = await t.read_archive_seed.ainvoke({"chapter": 1, "name": "甲"})
    assert "登场初始口癖" in out
    assert "句尾爱加「呢」，紧张时会重复最后两个字" in out


@pytest.mark.asyncio
async def test_read_seed_shows_no_verbal_tic_placeholder_when_unset(monkeypatch, tmp_path):
    """创建期没声明口癖 → cold_start 展示占位，不报错、不留空行误导 agent 以为字段不存在。"""
    _seed_context(monkeypatch, tmp_path)

    out = await t.read_archive_seed.ainvoke({"chapter": 1, "name": "甲"})
    assert "登场初始口癖" in out
    assert "（未设定）" in out


@pytest.mark.asyncio
async def test_read_seed_marks_timeline_active(monkeypatch, tmp_path):
    import engine.setup_chat.world_pipeline as wp
    wp._ACTIVE_TIMELINE_TARGET = None
    plot = [{"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "location": "屋内", "description": "甲登场"}]}]
    _seed_context(monkeypatch, tmp_path, plot=plot)

    await t.read_archive_seed.ainvoke({"chapter": 1, "name": "甲"})
    assert wp._ACTIVE_TIMELINE_TARGET == (1, "甲")


@pytest.mark.asyncio
async def test_read_seed_absent_character_does_not_mark_active(monkeypatch, tmp_path):
    import engine.setup_chat.world_pipeline as wp
    wp._ACTIVE_TIMELINE_TARGET = None
    _patch(monkeypatch, tmp_path)

    await t.read_archive_seed.ainvoke({"chapter": 1, "name": "乙"})  # 乙 not in plot
    assert wp._ACTIVE_TIMELINE_TARGET is None


@pytest.mark.asyncio
async def test_write_clears_timeline_active_on_success(monkeypatch, tmp_path):
    import engine.setup_chat.world_pipeline as wp
    _patch(monkeypatch, tmp_path)
    wp._ACTIVE_TIMELINE_TARGET = (1, "甲")

    await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"personality": "外冷内热"},
    })
    assert wp._ACTIVE_TIMELINE_TARGET is None


@pytest.mark.asyncio
async def test_write_keeps_timeline_active_on_validation_failure(monkeypatch, tmp_path):
    import engine.setup_chat.world_pipeline as wp
    _patch(monkeypatch, tmp_path)
    wp._ACTIVE_TIMELINE_TARGET = (1, "甲")

    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"personality": "   "},  # rejected: blank personality
    })
    assert "未写入" in out
    assert wp._ACTIVE_TIMELINE_TARGET == (1, "甲")


def test_allowed_delta_fields_no_longer_includes_state_or_clothing():
    assert "state" not in t._delta_allowed_fields()
    assert "clothing" not in t._delta_allowed_fields()


@pytest.mark.asyncio
async def test_write_drops_state_and_clothing_and_archive_has_neither(monkeypatch, tmp_path):
    """state/clothing 提交后被剥掉（计入 dropped 提示），archive 里也不会靠 plot 的
    known_clothing 回填出 clothing。"""
    captured = _patch(monkeypatch, tmp_path)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {
            "self_ref": {"_default": ["爱丽丝"]},
            "sliders": {"侵蚀度": {"level": 1, "text": "动摇"}},
            "state": {"physiology": "如常", "psychology": "平静"},
            "clothing": "校服",
        },
    })
    assert "已忽略槽外字段" in out
    assert "state" in out and "clothing" in out
    arch = captured["archive"]
    assert "state" not in arch
    assert "clothing" not in arch


@pytest.mark.asyncio
async def test_write_persists_race(monkeypatch, tmp_path):
    captured = _patch(monkeypatch, tmp_path)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"race": "精灵"},
    })
    assert "未写入" not in out
    from context import character_timeline
    snaps = character_timeline.load_timeline("甲")["snapshots"]
    assert snaps[-1]["delta"]["race"] == "精灵"
    assert captured["archive"]["race"] == "精灵"


@pytest.mark.asyncio
async def test_write_persists_identity_background(monkeypatch, tmp_path):
    captured = _patch(monkeypatch, tmp_path)
    out = await t.write_character_archive.ainvoke({
        "chapter": 1, "name": "甲",
        "profile": {"identity_background": "隐藏身份是王室私生女"},
    })
    assert "未写入" not in out
    assert captured["archive"]["identity_background"] == "隐藏身份是王室私生女"


def test_normalize_delta_keeps_race_and_identity_background():
    delta = {"race": "精灵", "identity_background": "隐藏身份", "state": {"psychology": "x"}}
    out, dropped = t._normalize_delta(delta)
    assert out["race"] == "精灵"
    assert out["identity_background"] == "隐藏身份"
    assert "state" not in out


@pytest.mark.asyncio
async def test_generate_one_chapter_append_schedules_cascade_for_new_chapter(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲"], "archetypes": ["同质堕落型"]},
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["甲"] if "甲" in text else [],
    )
    calls = []
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade",
        lambda min_chapter, names=None: calls.append((min_chapter, names)),
    )
    import repositories
    n = len(repositories.get_plot_repo().list_raw())
    await t.generate_one_chapter.ainvoke({
        "chapter_index": n + 1, "title": "新章", "core_xp": ["承"],
        "stages": [{"stage_num": 1, "title": "s", "location": "L", "description": "甲登场",
                    "characters": {"甲": {}}}],
    })
    assert calls == [(n + 1, ["甲"])]


@pytest.mark.asyncio
async def test_edit_character_schedules_full_rebuild_for_that_character(monkeypatch, tmp_path):
    from engine.setup.cast.stance_schema import physique_slots

    _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "engine.archive.sliders.character_rubrics",
        lambda _name: {"侵蚀度": {"0": "a", "1": "b", "2": "c"}},
    )
    #race validation reads world_bible races via _load_world_race_names when not passed
    #explicitly -- mocked here so this test doesn't depend on whichever novel's live world
    #data happens to be active in the running environment (test/product data coupling
    #tracked separately in TODO.md's "测试数据与产品数据解耦" item).
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator._load_world_race_names", lambda: ["人"],
    )
    calls = []
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade",
        lambda min_chapter, names=None, **_kwargs: calls.append((min_chapter, names)),
    )
    await t.edit_character.ainvoke({
        "name": "甲", "given_name": "甲", "role": "同质堕落型", "gender": "female",
        "race": "人",
        "causal_anchors": {"执念": "复仇", "渴望": "认同"},
        "physique": {k: "x" for k in physique_slots("female")},
        "clothing_color_palette": ["黑"], "clothing_materials": ["皮革"],
        "clothing_signature_outfit": "黑色皮革风日常常服",
        "clothing_accessories": ["皮质腕带"],
        "sliders": {"侵蚀度": {"level": 1, "text": "动摇", "levels": {"0": "a", "1": "b", "2": "c"}}},
        "personality": "改动后的性格",
        "identity_background": "出身平平，家境普通",
        "武器": "尚待观察",
        "流派": "尚待观察",
        "身份": "尚待观察",
    })
    assert calls == [(1, "甲")]
