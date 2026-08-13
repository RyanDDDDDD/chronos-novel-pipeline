"""scripts/rename_lore_sliders_init.py: retire the sliders_init key across every novel --
rename it on lore records, fold it into resolved archives as the sliders baseline."""
import json

import pytest

from scripts.rename_lore_sliders_init import rename_sliders_init_to_sliders
from tests.conftest import seed_registry_novel


@pytest.fixture
def novels_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.delenv("CHRONOS_ACTIVE_NOVEL", raising=False)
    return tmp_path


def _seed_novel(novels_root, nid: str, name: str, lore: list[dict] | None = None) -> None:
    seed_registry_novel(novels_root, nid, name)
    if lore is not None:
        (novels_root / nid / "lore" / "character_lore_library.json").write_text(
            json.dumps(lore, ensure_ascii=False), encoding="utf-8"
        )


def _seed_archive(novels_root, nid: str, rel: str, archive: dict) -> None:
    p = novels_root / nid / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(archive, ensure_ascii=False), encoding="utf-8")


def test_renames_sliders_init_across_novels_and_skips_already_migrated(novels_root):
    _seed_novel(novels_root, "novel-a", "甲部", lore=[
        {"name": "小夜", "given_name": "小夜", "role": "始祖",
         "causal_anchors": {}, "sliders_init": {"转化度": {"level": 2, "text": "完全转化"}}},
    ])
    _seed_novel(novels_root, "novel-b", "乙部", lore=[
        {"name": "甲", "given_name": "甲", "role": "同质堕落型",
         "causal_anchors": {}, "sliders": {"侵蚀度": {"level": 0, "text": "未触碰"}}},
    ])
    _seed_novel(novels_root, "novel-c", "丙部")  # no lore file at all yet

    affected = rename_sliders_init_to_sliders()

    assert set(affected) == {"novel-a"}
    assert affected["novel-a"]["lore"] == ["小夜"]
    saved_a = json.loads((novels_root / "novel-a" / "lore" / "character_lore_library.json")
                         .read_text(encoding="utf-8"))
    assert saved_a[0]["sliders"] == {"转化度": {"level": 2, "text": "完全转化"}}
    assert "sliders_init" not in saved_a[0]
    saved_b = json.loads((novels_root / "novel-b" / "lore" / "character_lore_library.json")
                         .read_text(encoding="utf-8"))
    assert saved_b[0]["sliders"] == {"侵蚀度": {"level": 0, "text": "未触碰"}}  # untouched


def test_folds_archive_sliders_init_into_sliders(novels_root):
    _seed_novel(novels_root, "novel-a", "甲部")
    #Archive with BOTH keys: resolved axis wins, baseline-only axis is filled in.
    _seed_archive(novels_root, "novel-a", "chapters/第1章/characters/甲_ch01_archive.json", {
        "name": "甲",
        "sliders_init": {"侵蚀度": {"level": 0, "text": "初"}, "警惕度": {"level": 3, "text": "戒备"}},
        "sliders": {"侵蚀度": {"level": 2, "text": "加深"}},
    })
    #Archive with only sliders_init (resolve never produced sliders): baseline becomes sliders.
    _seed_archive(novels_root, "novel-a", "chapters/第2章/characters/乙_ch02_archive.json", {
        "name": "乙",
        "sliders_init": {"侵蚀度": {"level": 1, "text": "动摇"}},
    })
    #setup_chat snapshot copies (archive AND lore) are under the novel dir too -- also migrated.
    _seed_archive(novels_root, "novel-a",
                  "setup_chat/snapshot/files/chapters/第1章/characters/甲_ch01_archive.json", {
        "name": "甲", "sliders_init": {"侵蚀度": {"level": 0, "text": "初"}},
    })
    snap_lore = novels_root / "novel-a" / "setup_chat/snapshot/files/lore"
    snap_lore.mkdir(parents=True)
    (snap_lore / "character_lore_library.json").write_text(json.dumps([
        {"name": "甲", "sliders_init": {"侵蚀度": {"level": 0, "text": "初"}}},
    ], ensure_ascii=False), encoding="utf-8")

    affected = rename_sliders_init_to_sliders()

    assert len(affected["novel-a"]["archives"]) == 3
    assert affected["novel-a"]["lore"] == ["甲"]  # from the snapshot lore copy
    snap_saved = json.loads((snap_lore / "character_lore_library.json").read_text(encoding="utf-8"))
    assert "sliders_init" not in snap_saved[0] and "sliders" in snap_saved[0]
    both = json.loads((novels_root / "novel-a" / "chapters/第1章/characters/甲_ch01_archive.json")
                      .read_text(encoding="utf-8"))
    assert "sliders_init" not in both
    assert both["sliders"]["侵蚀度"] == {"level": 2, "text": "加深"}   # resolved wins
    assert both["sliders"]["警惕度"] == {"level": 3, "text": "戒备"}   # baseline fills gap
    only = json.loads((novels_root / "novel-a" / "chapters/第2章/characters/乙_ch02_archive.json")
                      .read_text(encoding="utf-8"))
    assert "sliders_init" not in only
    assert only["sliders"] == {"侵蚀度": {"level": 1, "text": "动摇"}}
    snap = json.loads((novels_root / "novel-a" /
                       "setup_chat/snapshot/files/chapters/第1章/characters/甲_ch01_archive.json")
                      .read_text(encoding="utf-8"))
    assert "sliders_init" not in snap


def test_noop_when_no_novel_has_sliders_init(novels_root):
    _seed_novel(novels_root, "novel-a", "甲部", lore=[
        {"name": "甲", "given_name": "甲", "role": "x", "causal_anchors": {},
         "sliders": {"侵蚀度": {"level": 0, "text": "未触碰"}}},
    ])
    _seed_archive(novels_root, "novel-a", "chapters/第1章/characters/甲_ch01_archive.json", {
        "name": "甲", "sliders": {"侵蚀度": {"level": 0, "text": "未触碰"}},
    })
    assert rename_sliders_init_to_sliders() == {}


def test_noop_when_no_novels_exist(novels_root):
    assert rename_sliders_init_to_sliders() == {}
