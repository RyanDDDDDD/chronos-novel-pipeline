"""Tests for the upstream-write author guard (spec D13, §6 affected-set table)."""
import pytest
from engine.setup_chat import author_guard as ag


class TestAffectedRange:
    def test_auto_build_setup_affects_all(self):
        assert ag.affected_chapter_range("auto_build_setup", {}) == ag.ALL_CHAPTERS

    def test_open_ended_from_chapter(self):
        assert ag.affected_chapter_range("generate_one_chapter", {"chapter": 3}) == (3, 10**9)
        assert ag.affected_chapter_range("write_character_archive", {"chapter": 5, "name": "x"}) == (5, 10**9)

    def test_single_chapter_tools(self):
        for name in ("patch_chapter", "write_chapter_skeleton", "patch_text_fragment"):
            assert ag.affected_chapter_range(name, {"chapter": 7}) == (7, 7)

    def test_auto_expand_skeleton_affects_single_chapter(self):
        assert ag.affected_chapter_range("auto_expand_skeleton", {"chapter": 3}) == (3, 3)

    def test_chapter_arg_missing_falls_back_to_all(self):
        # Defensive: a plot tool without a parseable chapter must not silently skip the guard.
        assert ag.affected_chapter_range("patch_chapter", {}) == ag.ALL_CHAPTERS

    def test_non_plot_write_tools_affect_nothing(self):
        assert ag.affected_chapter_range("construct_world", {"features": []}) is None
        assert ag.affected_chapter_range("add_character", {"name": "x"}) is None
        assert ag.affected_chapter_range("some_skill_tool", {}) is None


class TestGuardRegistry:
    @pytest.mark.asyncio
    async def test_unregistered_guard_is_noop(self):
        ag.set_author_guard(None)
        await ag.stop_author_if_affected(1, 1, "reason")  # must not raise

    @pytest.mark.asyncio
    async def test_registered_guard_receives_args(self):
        calls: list[tuple] = []

        async def fake_guard(lo: int, hi: int, reason: str) -> None:
            calls.append((lo, hi, reason))

        ag.set_author_guard(fake_guard)
        try:
            await ag.stop_author_if_affected(3, 3, "第 3 章设定变更")
        finally:
            ag.set_author_guard(None)
        assert calls == [(3, 3, "第 3 章设定变更")]
