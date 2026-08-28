"""Novel archive service: list/create/rename/delete/set_active/ensure_initialized."""
import asyncio
import json

import api.services.novels as nv
import pytest
from repositories.registry_store import get_registry_connection


@pytest.fixture
def novels_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.delenv("CHRONOS_ACTIVE_NOVEL", raising=False)
    return tmp_path


@pytest.fixture(autouse=True)
def sync_novel_trash(monkeypatch):
    """The unit test does not have a scheduler loop, and it is released synchronously and trash is moved immediately after marking."""

    def _sync(nid: str, release) -> None:
        async def _run() -> None:
            await release()
            nv.move_novel_to_trash(nid)

        asyncio.run(_run())

    monkeypatch.setattr(nv, "_schedule_trash_move", _sync)


def _seed(novels_root, nid="default", name="默认", *, active: bool = True):
    d = novels_root / nid
    (d / "lore").mkdir(parents=True)
    (d / "plot").mkdir()
    (d / "chapters").mkdir()
    conn = get_registry_connection()
    conn.execute(
        "INSERT INTO novels (id, name, created_at, is_active) VALUES (?, ?, ?, ?)",
        (nid, name, "2020-01-01T00:00:00+00:00", 1 if active else 0),
    )
    conn.commit()
    nv._write_default_novel_settings(nid)
    return d


def test_list_and_active(novels_root):
    _seed(novels_root)
    assert nv.list_novels() == [{"id": "default", "name": "默认", "active": True, "pinned": False}]


def test_pin_novel_sorts_to_top_and_sets_pinned_flag(novels_root):
    _seed(novels_root, nid="a", name="A小说", active=False)
    _seed(novels_root, nid="b", name="B小说", active=True)
    nv.set_novel_pinned("a", True)
    novels = nv.list_novels()
    assert [n["id"] for n in novels] == ["a", "b"]
    assert novels[0]["pinned"] is True
    assert novels[1]["pinned"] is False


def test_unpin_novel_returns_to_name_order(novels_root):
    _seed(novels_root, nid="a", name="A小说", active=False)
    _seed(novels_root, nid="b", name="B小说", active=True)
    nv.set_novel_pinned("a", True)
    nv.set_novel_pinned("a", False)
    assert [n["id"] for n in nv.list_novels()] == ["a", "b"]
    assert all(not n["pinned"] for n in nv.list_novels())


def test_multiple_pinned_novels_most_recently_pinned_first(novels_root):
    _seed(novels_root, nid="a", name="A小说", active=False)
    _seed(novels_root, nid="b", name="B小说", active=False)
    _seed(novels_root, nid="c", name="C小说", active=True)
    nv.set_novel_pinned("a", True)
    nv.set_novel_pinned("b", True)
    assert [n["id"] for n in nv.list_novels()] == ["b", "a", "c"]


def test_pin_unknown_novel_raises(novels_root):
    _seed(novels_root)
    with pytest.raises(ValueError):
        nv.set_novel_pinned("nope", True)


def test_create_blank_builds_empty_dirs(novels_root):
    _seed(novels_root)
    nid = nv.create_novel("第二部", clone=False)
    nd = novels_root / nid
    #lore/plot now live in chronos.sqlite3 (created lazily on first SqliteStore access) --
    #create_novel no longer pre-creates empty lore/plot directories for them.
    assert (nd / "chapters").is_dir()
    assert not (nd / "lore").exists()
    assert not (nd / "plot").exists()
    assert nv.get_novel_name(nid) == "第二部"


def test_create_clone_copies_characters(novels_root):
    d = _seed(novels_root)
    (d / "lore" / "character_lore_library.json").write_text('[{"name":"旧"}]', encoding="utf-8")
    nid = nv.create_novel("变体", clone=True)
    assert (novels_root / nid / "lore" / "character_lore_library.json").is_file()


def test_copy_novel_from_non_active_preserves_lore(novels_root):
    _seed(novels_root, nid="default", name="默认")
    other = novels_root / "book-b"
    other.mkdir()
    (other / "lore").mkdir()
    (other / "plot").mkdir()
    (other / "chapters").mkdir()
    (other / "lore" / "character_lore_library.json").write_text('[{"name":"乙"}]', encoding="utf-8")
    conn = get_registry_connection()
    conn.execute(
        "INSERT INTO novels (id, name, created_at, is_active) VALUES (?, ?, ?, ?)",
        ("book-b", "乙", "2020-01-01T00:00:00+00:00", 0),
    )
    conn.commit()
    nv.set_prose_style("book-b", "cold-restrained", "冷")
    nv.set_source_franchise("book-b", " Blue Archive ")
    (other / "setup_chat").mkdir()
    (other / "setup_chat" / "checkpoint.sqlite").write_text("x", encoding="utf-8")
    nid = nv.copy_novel("book-b", "乙副本")
    dst = novels_root / nid
    assert json.loads((dst / "lore" / "character_lore_library.json").read_text(encoding="utf-8")) == [{"name": "乙"}]
    assert nv.get_novel_name(nid) == "乙副本"
    assert nv.get_prose_style(nid) == {"preset": "cold-restrained", "custom_addendum": "冷"}
    assert nv.get_source_franchise(nid) == "Blue Archive"
    assert not (dst / "setup_chat").exists()


def test_copy_novel_copies_vector_chunks_via_chronos_sqlite3(novels_root):
    _seed(novels_root, nid="default", name="默认")
    other = novels_root / "book-b"
    (other / "lore").mkdir(parents=True)
    (other / "plot").mkdir()
    (other / "chapters").mkdir()
    conn = get_registry_connection()
    conn.execute(
        "INSERT INTO novels (id, name, created_at, is_active) VALUES (?, ?, ?, ?)",
        ("book-b", "乙", "2020-01-01T00:00:00+00:00", 0),
    )
    conn.commit()

    from repositories.sqlite_store import get_connection as get_novel_db
    from utils.paths import novel_db_path

    db = get_novel_db(novel_db_path("book-b"))
    db.execute(
        "INSERT INTO vector_chunks (collection, id, document, metadata_json, embedding) "
        "VALUES ('setup_research', 'c1', '一条研究资料', '{}', X'00000000')",
    )
    db.commit()

    nid = nv.copy_novel("book-b", "乙副本")

    copied_row = get_novel_db(novel_db_path(nid)).execute(
        "SELECT document FROM vector_chunks WHERE collection = 'setup_research' AND id = 'c1'",
    ).fetchone()
    assert copied_row is not None
    assert copied_row[0] == "一条研究资料"


def test_copy_novel_unknown_raises(novels_root):
    _seed(novels_root)
    with pytest.raises(ValueError):
        nv.copy_novel("nope", "副本")


def test_set_active_switches(novels_root):
    _seed(novels_root)
    nid = nv.create_novel("第二部", clone=False)
    nv.set_active(nid)
    from utils.paths import active_novel_id
    assert active_novel_id() == nid


def test_set_active_unknown_raises(novels_root):
    _seed(novels_root)
    with pytest.raises(ValueError):
        nv.set_active("nope")


def test_delete_active_heals_to_remaining(novels_root):
    _seed(novels_root)  # active=default
    nid = nv.create_novel("第二部", clone=False)
    nv.delete_novel("default")  #What is deleted is active → should be allowed and cut to the first remaining part
    assert not (novels_root / "default").exists()
    assert (novels_root / ".trash" / "default").is_dir()
    from utils.paths import active_novel_id
    assert active_novel_id() == nid
    assert nv.list_novels() == [{"id": nid, "name": "第二部", "active": True, "pinned": False}]


def test_delete_moves_to_trash_with_timestamp_on_collision(novels_root):
    _seed(novels_root, nid="foo", name="Foo")
    nv.create_novel("bar", clone=False)
    trash = novels_root / ".trash" / "foo"
    trash.mkdir(parents=True)
    (trash / "novel.json").write_text("{}", encoding="utf-8")
    nv.delete_novel("foo")
    assert not (novels_root / "foo").exists()
    moved = [p.name for p in (novels_root / ".trash").iterdir() if p.name.startswith("foo")]
    assert len(moved) == 2
    assert any("-" in name for name in moved)


def test_delete_legacy_flag_then_move(novels_root):
    _seed(novels_root, nid="legacy", name="旧")
    nv.create_novel("keep", clone=False)
    conn = get_registry_connection()
    conn.execute(
        "UPDATE novels SET deleted_at = ? WHERE id = ?",
        ("2020-01-01T00:00:00+00:00", "legacy"),
    )
    conn.commit()
    nv.delete_novel("legacy")
    assert not (novels_root / "legacy").exists()
    assert (novels_root / ".trash" / "legacy").is_dir()


def test_delete_last_blocked(novels_root):
    _seed(novels_root)
    with pytest.raises(ValueError):
        nv.delete_novel("default")  #Only one left, cannot be deleted


def test_delete_unknown_raises(novels_root):
    _seed(novels_root)
    nv.create_novel("第二部", clone=False)
    with pytest.raises(ValueError):
        nv.delete_novel("nope")


def test_rename(novels_root):
    _seed(novels_root)
    nv.rename_novel("default", "新名")
    assert nv.list_novels()[0]["name"] == "新名"


def test_ensure_initialized_creates_blank_default_when_empty(novels_root):
    nv.ensure_initialized()
    assert (novels_root / "default" / "chapters").is_dir()
    assert not (novels_root / "default" / "lore").exists()
    assert not (novels_root / "default" / "plot").exists()
    from utils.paths import active_novel_id
    assert active_novel_id() == "default"


def test_ensure_initialized_heals_dangling_active(novels_root):
    _seed(novels_root, nid="bookA", name="A")
    conn = get_registry_connection()
    conn.execute("UPDATE novels SET is_active = 0")
    conn.execute(
        "INSERT INTO novels (id, name, created_at, is_active, deleted_at)"
        " VALUES (?, ?, ?, ?, ?)",
        ("ghost", "Ghost", "2020-01-01T00:00:00+00:00", 1, None),
    )
    conn.commit()
    nv.ensure_initialized()
    from utils.paths import active_novel_id
    assert active_novel_id() == "bookA"


def test_create_writes_default_prose_style(novels_root):
    _seed(novels_root)
    nid = nv.create_novel("测试", clone=False)
    assert nv.get_prose_style(nid) == {"preset": "plain-direct", "custom_addendum": ""}


def test_rename_preserves_prose_style(novels_root):
    _seed(novels_root)
    nv.set_prose_style("default", "cold-restrained", "更冷")
    nv.rename_novel("default", "新名")
    assert nv.get_novel_name("default") == "新名"
    assert nv.get_prose_style("default") == {"preset": "cold-restrained", "custom_addendum": "更冷"}


def test_set_get_prose_style_roundtrip(novels_root):
    _seed(novels_root)
    nv.set_prose_style("default", "cold-restrained", "更冷")
    assert nv.get_prose_style("default") == {"preset": "cold-restrained", "custom_addendum": "更冷"}


def test_source_franchise_roundtrip(novels_root):
    _seed(novels_root)
    assert nv.get_source_franchise("default") == ""
    nv.set_source_franchise("default", "  Blue Archive  ")
    assert nv.get_source_franchise("default") == "Blue Archive"
    nv.set_source_franchise("default", "")
    assert nv.get_source_franchise("default") == ""


def test_set_source_franchise_unknown_novel_raises(novels_root):
    _seed(novels_root)
    with pytest.raises(ValueError):
        nv.set_source_franchise("no-such-novel", "X")


def test_get_sandbox_dialogue_turn_count_defaults_to_none(novels_root):
    _seed(novels_root)
    assert nv.get_sandbox_dialogue_turn_count("default") is None


def test_set_get_sandbox_dialogue_turn_count_roundtrip(novels_root):
    _seed(novels_root)
    nv.set_sandbox_dialogue_turn_count("default", 5)
    assert nv.get_sandbox_dialogue_turn_count("default") == 5


def test_set_sandbox_dialogue_turn_count_none_clears_to_auto(novels_root):
    _seed(novels_root)
    nv.set_sandbox_dialogue_turn_count("default", 5)
    nv.set_sandbox_dialogue_turn_count("default", None)
    assert nv.get_sandbox_dialogue_turn_count("default") is None


def test_get_sandbox_dialogue_turn_count_out_of_range_treated_as_none(novels_root):
    _seed(novels_root)
    nv._merge_novel_settings("default", {"sandbox_dialogue_turn_count": 21})
    assert nv.get_sandbox_dialogue_turn_count("default") is None


def test_set_sandbox_dialogue_turn_count_unknown_novel_raises(novels_root):
    _seed(novels_root)
    with pytest.raises(ValueError):
        nv.set_sandbox_dialogue_turn_count("nope", 5)


def test_get_novel_name_reads_display_name(novels_root):
    _seed(novels_root, nid="nov1", name="赛博都市")
    assert nv.get_novel_name("nov1") == "赛博都市"


def test_get_novel_name_falls_back_to_id_when_missing():
    assert nv.get_novel_name("no-such-novel") == "no-such-novel"
