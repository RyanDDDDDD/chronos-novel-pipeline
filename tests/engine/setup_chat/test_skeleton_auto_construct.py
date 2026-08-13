import pytest

from engine.setup_chat import skeleton_auto_construct as sac


def _valid_plan_json(stage_nums: list[int]) -> str:
    stages = ", ".join(
        f'{{"stage_num": {n}, "lens_angles": ["角度A"], "extensions": [], "overview": ""}}'
        for n in stage_nums
    )
    return f'{{"direction": "主线推进", "stages": [{stages}]}}'


@pytest.mark.asyncio
async def test_draft_skeleton_plan_parses_valid_json_first_try(monkeypatch):
    monkeypatch.setattr(sac, "_skill_body", lambda name: f"[SKILL:{name}]")

    async def call_llm(_system: str, _user: str) -> str:
        return _valid_plan_json([1, 2])

    plan, errors = await sac.draft_skeleton_plan(3, [1, 2], call_llm)
    assert errors == []
    assert plan is not None
    assert plan["direction"] == "主线推进"
    assert {s["stage_num"] for s in plan["stages"]} == {1, 2}


@pytest.mark.asyncio
async def test_draft_skeleton_plan_system_prompt_uses_skeleton_expansion_skill(monkeypatch):
    monkeypatch.setattr(
        sac, "_skill_body",
        lambda name: f"[SKILL:{name}]" if name == "skeleton-expansion" else "",
    )
    seen = {}

    async def call_llm(system: str, user: str) -> str:
        seen["system"] = system
        seen["user"] = user
        return _valid_plan_json([1])

    await sac.draft_skeleton_plan(3, [1], call_llm)
    assert "[SKILL:skeleton-expansion]" in seen["system"]
    assert "present_choices" in seen["system"]  # the AUTO override must forbid it explicitly


@pytest.mark.asyncio
async def test_draft_skeleton_plan_rejects_stage_num_mismatch_then_succeeds(monkeypatch):
    monkeypatch.setattr(sac, "_skill_body", lambda name: "")
    calls: list[str] = []

    async def call_llm(_system: str, user: str) -> str:
        calls.append(user)
        if len(calls) == 1:
            return _valid_plan_json([1])  # missing stage 2
        return _valid_plan_json([1, 2])

    plan, errors = await sac.draft_skeleton_plan(3, [1, 2], call_llm, max_redo=1)
    assert errors == []
    assert plan is not None
    assert len(calls) == 2
    assert "未通过" in calls[1] or "校验" in calls[1] or "stage" in calls[1].lower()


@pytest.mark.asyncio
async def test_draft_skeleton_plan_exhausts_retries_returns_errors(monkeypatch):
    monkeypatch.setattr(sac, "_skill_body", lambda name: "")

    async def call_llm(_system: str, _user: str) -> str:
        return "不是JSON"

    plan, errors = await sac.draft_skeleton_plan(3, [1], call_llm, max_redo=1)
    assert plan is None
    assert errors != []


@pytest.mark.asyncio
async def test_run_auto_expand_skeleton_writes_direction_then_stages_in_order(monkeypatch):
    call_order: list[str] = []

    monkeypatch.setattr(sac, "_chapter_stage_nums", lambda ch: [1, 2])
    monkeypatch.setattr(sac, "_chapter_remaining_stage_nums", lambda ch: [1, 2])
    monkeypatch.setattr(sac, "_is_direction_set", lambda ch: False)

    async def fake_draft(chapter, stage_nums, call_llm, **kw):
        return {
            "direction": "主线推进",
            "stages": [
                {"stage_num": 2, "lens_angles": ["a"], "extensions": [], "overview": ""},
                {"stage_num": 1, "lens_angles": ["b"], "extensions": [], "overview": ""},
            ],
        }, []

    def fake_set_chapter_direction(chapter, direction):
        call_order.append(f"direction:{chapter}:{direction}")

    def fake_set_stage_lens(chapter, stage_num, angles):
        call_order.append(f"lens:{stage_num}")

    def fake_set_stage_extensions(chapter, stage_num, extensions):
        call_order.append(f"extensions:{stage_num}")

    async def fake_write_chapter_skeleton(chapter, stage_num, overview):
        call_order.append(f"write:{stage_num}")
        return f"已生成第 {chapter} 章骨架（stage{stage_num}）。"

    monkeypatch.setattr(sac, "draft_skeleton_plan", fake_draft)
    monkeypatch.setattr(sac, "_set_chapter_direction", fake_set_chapter_direction)
    monkeypatch.setattr(sac, "_set_stage_lens", fake_set_stage_lens)
    monkeypatch.setattr(sac, "_set_stage_extensions", fake_set_stage_extensions)
    monkeypatch.setattr(sac, "_write_chapter_skeleton_core", fake_write_chapter_skeleton)

    async def call_llm(_s: str, _u: str) -> str:
        return "{}"

    summary = await sac.run_auto_expand_skeleton(3, call_llm)
    assert call_order == [
        "direction:3:主线推进",
        "lens:1", "extensions:1", "write:1",
        "lens:2", "extensions:2", "write:2",
    ]
    assert "3" in summary


@pytest.mark.asyncio
async def test_run_auto_expand_skeleton_no_plot_returns_error(monkeypatch):
    monkeypatch.setattr(sac, "_chapter_stage_nums", lambda ch: [])

    async def call_llm(_s: str, _u: str) -> str:
        return "{}"

    summary = await sac.run_auto_expand_skeleton(99, call_llm)
    assert "plot" in summary or "无 stage" in summary or "不存在" in summary


@pytest.mark.asyncio
async def test_run_auto_expand_skeleton_skips_failed_stage_continues(monkeypatch):
    monkeypatch.setattr(sac, "_chapter_stage_nums", lambda ch: [1, 2])
    monkeypatch.setattr(sac, "_chapter_remaining_stage_nums", lambda ch: [1, 2])
    monkeypatch.setattr(sac, "_is_direction_set", lambda ch: False)

    async def fake_draft(chapter, stage_nums, call_llm, **kw):
        return {
            "direction": "x",
            "stages": [
                {"stage_num": 1, "lens_angles": ["a"], "extensions": [], "overview": ""},
                {"stage_num": 2, "lens_angles": ["b"], "extensions": [], "overview": ""},
            ],
        }, []

    written: list[int] = []

    async def fake_write(chapter, stage_num, overview):
        if stage_num == 1:
            return f"第 {chapter} 章 stage 1 分拍生成失败：模拟失败"
        written.append(stage_num)
        return f"已生成第 {chapter} 章骨架（stage{stage_num}）。"

    monkeypatch.setattr(sac, "draft_skeleton_plan", fake_draft)
    monkeypatch.setattr(sac, "_set_chapter_direction", lambda *a: None)
    monkeypatch.setattr(sac, "_set_stage_lens", lambda *a: None)
    monkeypatch.setattr(sac, "_set_stage_extensions", lambda *a: None)
    monkeypatch.setattr(sac, "_write_chapter_skeleton_core", fake_write)

    async def call_llm(_s: str, _u: str) -> str:
        return "{}"

    summary = await sac.run_auto_expand_skeleton(3, call_llm)
    assert written == [2]
    assert "失败" in summary


@pytest.mark.asyncio
async def test_run_auto_expand_skeleton_resumes_only_remaining_stages(monkeypatch):
    """Chapter has stage 1 already expanded (manual progress before a mid-turn switch into
    AUTO) -- resuming must only plan/write stage 2, never touch stage 1 again."""
    monkeypatch.setattr(sac, "_chapter_stage_nums", lambda ch: [1, 2])
    monkeypatch.setattr(sac, "_chapter_remaining_stage_nums", lambda ch: [2])
    monkeypatch.setattr(sac, "_is_direction_set", lambda ch: False)

    seen_stage_nums: list[int] = []

    async def fake_draft(chapter, stage_nums, call_llm, **kw):
        seen_stage_nums.extend(stage_nums)
        return {
            "direction": "主线推进",
            "stages": [{"stage_num": 2, "lens_angles": ["a"], "extensions": [], "overview": ""}],
        }, []

    written: list[int] = []

    async def fake_write(chapter, stage_num, overview):
        written.append(stage_num)
        return f"已生成第 {chapter} 章骨架（stage{stage_num}）。"

    monkeypatch.setattr(sac, "draft_skeleton_plan", fake_draft)
    monkeypatch.setattr(sac, "_set_chapter_direction", lambda *a: None)
    monkeypatch.setattr(sac, "_set_stage_lens", lambda *a: None)
    monkeypatch.setattr(sac, "_set_stage_extensions", lambda *a: None)
    monkeypatch.setattr(sac, "_write_chapter_skeleton_core", fake_write)

    async def call_llm(_s: str, _u: str) -> str:
        return "{}"

    await sac.run_auto_expand_skeleton(3, call_llm)
    assert seen_stage_nums == [2]
    assert written == [2]


@pytest.mark.asyncio
async def test_run_auto_expand_skeleton_does_not_overwrite_existing_direction(monkeypatch):
    monkeypatch.setattr(sac, "_chapter_stage_nums", lambda ch: [1, 2])
    monkeypatch.setattr(sac, "_chapter_remaining_stage_nums", lambda ch: [2])
    monkeypatch.setattr(sac, "_is_direction_set", lambda ch: True)

    async def fake_draft(chapter, stage_nums, call_llm, **kw):
        return {
            "direction": "freshly drafted, should be discarded",
            "stages": [{"stage_num": 2, "lens_angles": ["a"], "extensions": [], "overview": ""}],
        }, []

    direction_calls: list[tuple] = []

    monkeypatch.setattr(sac, "draft_skeleton_plan", fake_draft)
    monkeypatch.setattr(sac, "_set_chapter_direction", lambda *a: direction_calls.append(a))
    monkeypatch.setattr(sac, "_set_stage_lens", lambda *a: None)
    monkeypatch.setattr(sac, "_set_stage_extensions", lambda *a: None)

    async def fake_write(chapter, stage_num, overview):
        return f"已生成第 {chapter} 章骨架（stage{stage_num}）。"

    monkeypatch.setattr(sac, "_write_chapter_skeleton_core", fake_write)

    async def call_llm(_s: str, _u: str) -> str:
        return "{}"

    summary = await sac.run_auto_expand_skeleton(3, call_llm)
    assert direction_calls == []  # existing direction never overwritten
    assert "freshly drafted" not in summary


@pytest.mark.asyncio
async def test_run_auto_expand_skeleton_already_complete_returns_noop_message(monkeypatch):
    monkeypatch.setattr(sac, "_chapter_stage_nums", lambda ch: [1, 2])
    monkeypatch.setattr(sac, "_chapter_remaining_stage_nums", lambda ch: [])

    async def call_llm(_s: str, _u: str) -> str:
        return "{}"

    summary = await sac.run_auto_expand_skeleton(3, call_llm)
    assert "已全部展开" in summary or "无需" in summary
