from context.pre_inject import (
    filter_for_segment,
    format_context,
    narrow_archive_stages,
)


def _sample_archive_pi():
    return {
        "character_archive": {
            "角色A": {
                "name": "角色A",
                "archetype": "孤傲型",
                "clothing": "锦缎长裙",
                "state": {"physiology": "生理1", "psychology": "心理1"},
            }
        }
    }


def testnarrow_archive_stages_nested_path():
    """Click path state.physiology: only retains that nested subfield, discards archetype/clothing/other state keys."""
    out = narrow_archive_stages(_sample_archive_pi(), keep_paths=["state.physiology"])
    arch = out["character_archive"]["角色A"]
    assert arch == {"state": {"physiology": "生理1"}}
    assert "archetype" not in arch
    assert "clothing" not in arch
    assert "psychology" not in arch["state"]


def testnarrow_archive_stages_top_level_path():
    """Click path clothing: keep only clothing, discard state/archetype."""
    out = narrow_archive_stages(_sample_archive_pi(), keep_paths=["clothing"])
    arch = out["character_archive"]["角色A"]
    assert arch == {"clothing": "锦缎长裙"}
    assert "state" not in arch


def testnarrow_archive_stages_missing_path_skipped():
    """If the path is missing, the path will be skipped, no error will be reported, and empty keys will not be written."""
    out = narrow_archive_stages(_sample_archive_pi(), keep_paths=["nonexistent"])
    assert out["character_archive"]["角色A"] == {}

def testformat_context():
    data = {
        "outline": "大纲内容",
        "character_archive": {
            "char1": "档案内容1",
            "char2": "档案内容2",
        },
    }
    result = format_context(data)
    assert "## 剧情大纲" in result
    assert "大纲内容" in result
    assert "## 角色专属档案（含各 Stage 状态）" in result
    assert "### char1\n档案内容1" in result
    assert "### char2\n档案内容2" in result

def testfilter_for_segment_filters_characters():
    data = {
        "phase_timeline": {"角色A": "Phase 1 ...", "角色B": "Phase 2 ...", "角色C": "Phase 3 ..."},
        "character_lore": {"角色A": "某宗门少主", "角色B": "某楼花魁", "角色C": "某族神女"},
        "outline": "本段大纲",
    }
    result = filter_for_segment(data, ["角色A"])
    assert set(result["phase_timeline"].keys()) == {"角色A"}
    assert set(result["character_lore"].keys()) == {"角色A"}
    assert result["outline"] == "本段大纲"  #Non-dict fields are left intact


def testfilter_for_segment_fallback_when_no_match():
    data = {
        "phase_timeline": {"角色A": "Phase 1", "角色B": "Phase 2"},
    }
    #When seg_chars is an empty list, there is no match and falls back to the full size.
    result = filter_for_segment(data, [])
    assert result["phase_timeline"] == data["phase_timeline"]


def testfilter_for_segment_non_dict_values_pass_through():
    data = {
        "available_plugins": '[{"id": "UPP-03"}]',  #string, not per-character dict
        "phase_timeline": {"A": "data"},
    }
    result = filter_for_segment(data, ["A"])
    assert result["available_plugins"] == '[{"id": "UPP-03"}]'


def testformat_context_extra_labels():
    """
Keys in extra_labels take precedence over _LABEL_MAP, and unknown keys are returned unchanged."""
    data = {
        "my_custom_key": "自定义内容",
        "outline": "大纲",
    }
    result = format_context(data, extra_labels={"my_custom_key": "我的自定义标签"})
    assert "## 我的自定义标签" in result
    assert "自定义内容" in result
    assert "## 剧情大纲" in result


def testformat_context_unknown_key_falls_back_to_raw():
    """Keys that are not covered by neither extra_labels nor _LABEL_MAP are returned as-is as titles."""
    data = {"totally_unknown_key": "未知内容"}
    result = format_context(data)
    assert "## totally_unknown_key" in result
    assert "未知内容" in result


def testformat_context_extra_labels_overrides_core():
    """
extra_labels overwrites keys already in _LABEL_MAP (which takes precedence over the core map)."""
    data = {"outline": "大纲内容"}
    result = format_context(data, extra_labels={"outline": "覆盖标签"})
    assert "## 覆盖标签" in result
    assert "## 剧情大纲" not in result


def testformat_context_no_extra_labels_unchanged():
    """When extra_labels is not passed, the behavior is exactly the same as before."""
    data = {"outline": "大纲内容"}
    result_new = format_context(data)
    result_explicit_none = format_context(data, extra_labels=None)
    assert result_new == result_explicit_none
    assert "## 剧情大纲" in result_new
