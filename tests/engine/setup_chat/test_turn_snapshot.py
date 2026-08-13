"""Tests for call-level snapshot/restore (spec D2/D5/D7/D16)."""
import json
import os

import pytest
from engine.setup_chat import turn_snapshot as ts


@pytest.fixture()
def novel_dir(tmp_path, monkeypatch):
    """Fake active novel dir with domain files + excluded zones."""
    root = tmp_path / "novel"
    (root / "lore").mkdir(parents=True)
    (root / "lore" / "world_bible.json").write_text('{"v": 1}', encoding="utf-8")
    (root / "plot").mkdir()
    (root / "plot" / "plot_library.json").write_text('{"ch": 1}', encoding="utf-8")
    ch = root / "chapters" / "第1章"
    ch.mkdir(parents=True)
    (ch / "chapter_001_journal.ndjson").write_text("j1\n", encoding="utf-8")
    (ch / "第1章_主笔.md").write_text("prose", encoding="utf-8")
    (root / "chapters" / "_author_loop_graph.sqlite").write_text("cp", encoding="utf-8")
    (root / "chapters" / "_story_sandbox.sqlite").write_text("cp2", encoding="utf-8")
    (root / "setup_chat").mkdir()
    (root / "setup_chat" / "memory.json").write_text("{}", encoding="utf-8")
    (root / "session").mkdir()
    (root / "session" / "messages.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "novel")
    monkeypatch.setattr("utils.paths.active_novel_dir", lambda: str(root))
    monkeypatch.setattr("utils.paths.setup_chat_dir", lambda: str(root / "setup_chat"))
    return root


class TestExclusion:
    def test_setup_chat_and_session_excluded(self):
        assert ts.is_excluded("setup_chat/memory.json")
        assert ts.is_excluded("session/messages.json")

    def test_author_runtime_artifacts_excluded(self):
        assert ts.is_excluded("chapters/_author_loop_graph.sqlite")
        assert ts.is_excluded("chapters/_story_sandbox.sqlite")
        assert ts.is_excluded("chapters/第1章/chapter_001_journal.ndjson")
        assert ts.is_excluded("chapters/第1章/第1章_主笔.md")

    def test_domain_files_not_excluded(self):
        assert not ts.is_excluded("lore/world_bible.json")
        assert not ts.is_excluded("plot/plot_library.json")
        assert not ts.is_excluded("chapters/第1章/characters/hero.json")

    def test_windows_separators_normalized(self):
        assert ts.is_excluded("setup_chat\\memory.json")


class TestSnapshotRestore:
    def test_restore_reverts_modification_and_deletes_new_file(self, novel_dir):
        assert ts.take_snapshot(["call_1"], ["patch_chapter"])
        (novel_dir / "plot" / "plot_library.json").write_text('{"ch": 999}', encoding="utf-8")
        (novel_dir / "plot" / "stray.json").write_text("{}", encoding="utf-8")
        assert ts.restore_if_matches({"call_1"})
        assert json.loads((novel_dir / "plot" / "plot_library.json").read_text(encoding="utf-8")) == {"ch": 1}
        assert not (novel_dir / "plot" / "stray.json").exists()

    def test_restore_reverts_deletion(self, novel_dir):
        assert ts.take_snapshot(["call_1"], ["generate_one_chapter"])
        os.remove(novel_dir / "lore" / "world_bible.json")
        assert ts.restore_if_matches({"call_1"})
        assert (novel_dir / "lore" / "world_bible.json").exists()

    def test_excluded_zone_untouched_by_restore(self, novel_dir):
        assert ts.take_snapshot(["call_1"], ["patch_chapter"])
        (novel_dir / "setup_chat" / "memory.json").write_text('{"after": 1}', encoding="utf-8")
        (novel_dir / "chapters" / "第1章" / "chapter_001_journal.ndjson").write_text("j1\nj2\n", encoding="utf-8")
        assert ts.restore_if_matches({"call_1"})
        assert (novel_dir / "setup_chat" / "memory.json").read_text(encoding="utf-8") == '{"after": 1}'
        assert (novel_dir / "chapters" / "第1章" / "chapter_001_journal.ndjson").read_text(encoding="utf-8") == "j1\nj2\n"

    def test_id_mismatch_does_not_restore(self, novel_dir):
        assert ts.take_snapshot(["call_1"], ["patch_chapter"])
        (novel_dir / "plot" / "plot_library.json").write_text('{"ch": 999}', encoding="utf-8")
        assert not ts.restore_if_matches({"call_other"})
        assert "999" in (novel_dir / "plot" / "plot_library.json").read_text(encoding="utf-8")

    def test_no_snapshot_returns_false(self, novel_dir):
        assert not ts.restore_if_matches({"call_1"})

    def test_restore_failure_partway_never_deletes_a_currently_existing_file(self, novel_dir, monkeypatch):
        """Regression test for a real incident: a WinError-32-style failure partway through
        restore (e.g. a locked file that can't be copied back) must never leave a
        currently-existing file deleted with nothing restored in its place. The old
        delete-everything-then-copy-back order could do exactly that -- novel.json (an
        included, non-excluded file) got deleted in the first pass, then the copy-back pass
        hit a locked chapters/_story_sandbox.sqlite and aborted, leaving novel.json gone and
        the novel invisible in the sidebar list until manually recreated."""
        assert ts.take_snapshot(["call_1"], ["patch_chapter"])
        (novel_dir / "plot" / "plot_library.json").write_text('{"ch": 999}', encoding="utf-8")

        real_copy2 = ts.shutil.copy2

        def flaky_copy2(src, dst):
            if str(dst).endswith("world_bible.json"):
                raise OSError(32, "file in use")
            return real_copy2(src, dst)

        monkeypatch.setattr(ts.shutil, "copy2", flaky_copy2)

        assert not ts.restore_if_matches({"call_1"})
        # world_bible.json's own copy-back failed, but it must never have been deleted
        assert (novel_dir / "lore" / "world_bible.json").exists()
        # every other included file must still be present too, whichever state it's left in
        assert (novel_dir / "plot" / "plot_library.json").exists()


class TestResumeAttempts:
    def test_counter_persists(self, novel_dir):
        ts.take_snapshot(["call_1"], ["patch_chapter"])
        assert ts.resume_attempts() == 0
        assert ts.bump_resume_attempts() == 1
        assert ts.resume_attempts() == 1

    def test_counter_without_snapshot_is_zero(self, novel_dir):
        assert ts.resume_attempts() == 0


class TestTurnLevelSnapshotRestore:
    def test_restore_reverts_multiple_tool_calls_worth_of_writes(self, novel_dir):
        """Unlike restore_if_matches (call-level, only undoes the last call), this must undo
        everything written since the turn started, however many calls happened in between."""
        assert ts.snapshot_turn_start()
        (novel_dir / "plot" / "plot_library.json").write_text('{"ch": 2}', encoding="utf-8")
        (novel_dir / "lore" / "world_bible.json").write_text('{"v": 2}', encoding="utf-8")
        assert ts.restore_turn_start()
        assert json.loads((novel_dir / "plot" / "plot_library.json").read_text(encoding="utf-8")) == {"ch": 1}
        assert json.loads((novel_dir / "lore" / "world_bible.json").read_text(encoding="utf-8")) == {"v": 1}

    def test_excluded_zone_untouched(self, novel_dir):
        assert ts.snapshot_turn_start()
        (novel_dir / "setup_chat" / "memory.json").write_text('{"after": 1}', encoding="utf-8")
        assert ts.restore_turn_start()
        assert (novel_dir / "setup_chat" / "memory.json").read_text(encoding="utf-8") == '{"after": 1}'

    def test_no_snapshot_returns_false(self, novel_dir):
        assert ts.restore_turn_start() is False

    def test_does_not_share_storage_with_call_level_snapshot(self, novel_dir):
        """The two snapshot mechanisms must not clobber each other -- taking a call-level
        snapshot after a turn-level one must not corrupt the turn-level restore."""
        assert ts.snapshot_turn_start()
        (novel_dir / "plot" / "plot_library.json").write_text('{"ch": 2}', encoding="utf-8")
        assert ts.take_snapshot(["call_1"], ["patch_chapter"])
        (novel_dir / "plot" / "plot_library.json").write_text('{"ch": 3}', encoding="utf-8")
        assert ts.restore_turn_start()
        assert json.loads((novel_dir / "plot" / "plot_library.json").read_text(encoding="utf-8")) == {"ch": 1}
