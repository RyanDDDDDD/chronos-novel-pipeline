"""tests/scripts/test_cleanup_dynamic_state_fields.py"""
from scripts.cleanup_dynamic_state_fields import strip_dynamic_state_fields

from repo_test_helpers import seed_lore, seed_plot

_NOVEL_ID = "test-novel"


def _setup_novel(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", _NOVEL_ID)
    (tmp_path / _NOVEL_ID).mkdir(parents=True, exist_ok=True)
    import repositories

    repositories.init_repositories(_NOVEL_ID)


def test_strips_state_and_clothing_from_timeline_and_rebuilds_archive(tmp_path, monkeypatch):
    _setup_novel(tmp_path, monkeypatch)

    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
             "causal_anchors": {}, "sliders": {}}]
    plot = [{"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "title": "s", "location": "屋内", "description": "事件",
         "characters": {"甲": {}}},
    ]}]
    seed_lore(lore)
    seed_plot(plot)

    from context import character_timeline

    character_timeline.append_stage("甲", 1, 1, {
        "state": {"psychology": "旧心理", "physiology": "旧生理"},
        "clothing": "旧着装",
        "personality": "外冷内热",
    })

    persisted = {}
    import engine.setup_chat.tools as tools_mod
    monkeypatch.setattr(tools_mod, "_persist_archive",
                        lambda name, ch, arch: persisted.update({(name, ch): arch}))

    affected = strip_dynamic_state_fields()

    assert affected == {"甲": [1]}
    snaps = character_timeline.load_timeline("甲")["snapshots"]
    assert "state" not in snaps[-1]["delta"]
    assert "clothing" not in snaps[-1]["delta"]
    assert snaps[-1]["delta"]["personality"] == "外冷内热"  # 其余字段不受影响
    arch = persisted[("甲", 1)]
    assert "state" not in arch
    assert "clothing" not in arch
