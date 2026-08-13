import pytest
from engine.archive.archive_hook import (
    ArchiveDeltaContext,
    ArchiveDeltaHook,
    ArchiveEnrichContext,
    ArchiveEnrichHook,
    ArchivePhase,
    MergeStrategy,
)


def _delta_hook(name: str):
    from engine.archive.hook_loader import DELTA_HOOKS

    return next(h for h in DELTA_HOOKS if h.name == name)


def _enrich_hook(name: str):
    from engine.archive.hook_loader import ENRICH_HOOKS

    return next(h for h in ENRICH_HOOKS if h.name == name)


def test_delta_hook_defaults():
    class _H(ArchiveDeltaHook):
        name = "x"
        fields = ["foo"]

    h = _H()
    ctx = ArchiveDeltaContext(
        char={"name": "甲"}, chapter=1, relevant_stages=[],
        mode="rolling", prior=None, prior_appearances=[], call_llm=None,
    )
    assert h.phase == ArchivePhase.DELTA
    assert h.prompt_fragment(ctx) == ""
    assert h.stage_fragment(ctx, {"stage_num": 1}) == ""
    assert h.parse("foo", 42, ctx) == 42
    assert MergeStrategy.REPLACE == "replace"


def test_sliders_hook_fragment_and_parse(monkeypatch):
    from engine.archive.archive_hook import ArchiveDeltaContext
    from engine.archive.sliders import axes_of, render_axis_choices

    hook = _delta_hook("sliders")
    assert hook.fields == ["sliders"]
    assert hook.merge == {"sliders": "deep_ignore_none"}
    rubrics = {
        "投入": {"2": "理智旁观", "1": "近乎放弃"},
    }
    monkeypatch.setattr("engine.archive.sliders.character_rubrics", lambda _n: rubrics)
    ctx = ArchiveDeltaContext(
        char={"name": "甲", "role": "甲"}, chapter=1, relevant_stages=[],
        mode="rolling", prior=None, prior_appearances=[], call_llm=None,
    )
    frag = hook.prompt_fragment(ctx)
    assert "滑块档位" in frag
    ax = axes_of(rubrics)[0]
    choices = render_axis_choices(rubrics, ax)
    label = choices.split("  - ")[1].split("（")[0].strip() if "  - " in choices else "理智旁观"
    out = hook.parse("sliders", {ax: label}, ctx)
    assert isinstance(out, dict)


def test_physique_hook_prompt_fragment_rolling_uses_prior():
    hook = _delta_hook("physique")
    ctx = ArchiveDeltaContext(
        char={"name": "甲", "physique": {"胸部": "base胸", "腰腹": "base腰"}},
        chapter=1,
        relevant_stages=[],
        mode="rolling",
        prior={"physique": {"胸部": "prior胸", "腰腹": "prior腰"}},
        prior_appearances=[],
        call_llm=None,
    )
    frag = hook.prompt_fragment(ctx)
    assert frag
    assert "- 胸部（" in frag and ": prior胸" in frag
    assert "- 腰腹（" in frag and ": prior腰" in frag
    assert "base胸" not in frag


def test_physique_hook_prompt_fragment_cold_start_falls_back_to_base():
    hook = _delta_hook("physique")
    base = dict(
        char={"name": "甲", "physique": {"胸部": "base胸"}},
        chapter=1,
        relevant_stages=[],
        prior=None,
        prior_appearances=[],
        call_llm=None,
    )
    cold = hook.prompt_fragment(ArchiveDeltaContext(mode="cold_start", **base))
    rolling_no_prior = hook.prompt_fragment(ArchiveDeltaContext(mode="rolling", **base))
    assert "- 胸部（" in cold and ": base胸" in cold
    assert "- 胸部（" in rolling_no_prior and ": base胸" in rolling_no_prior


def test_physique_hook_prompt_fragment_empty_without_physique():
    hook = _delta_hook("physique")
    ctx = ArchiveDeltaContext(
        char={"name": "甲"},
        chapter=1,
        relevant_stages=[],
        mode="rolling",
        prior=None,
        prior_appearances=[],
        call_llm=None,
    )
    assert hook.prompt_fragment(ctx) == ""


def test_physique_hook_guard_drops_unknown(monkeypatch):
    from engine.archive.archive_hook import ArchiveDeltaContext

    hook = _delta_hook("physique")
    assert hook.fields == ["physique"]
    assert hook.merge == {"physique": "deep_remove_none"}
    #The character has a basic part slot (intimate) → guardrails take effect: self-created fields outside the part slot are discarded
    ctx = ArchiveDeltaContext(
        char={"name": "甲", "physique": {"intimate": "…"}}, chapter=1, relevant_stages=[],
        mode="rolling", prior=None, prior_appearances=[], call_llm=None,
    )
    out = hook.parse("physique", {"intimate": "异化A", "__definitely_unknown__": "x"}, ctx)
    assert out == {"intimate": "异化A"}


def test_delta_hooks_registry_and_strategies():
    from engine.archive.hook_loader import DELTA_HOOKS, collect_merge_strategies

    assert sorted(h.name for h in DELTA_HOOKS) == ["action", "physique", "sliders", "state"]
    strat = collect_merge_strategies()
    assert strat["sliders"] == "deep_ignore_none"
    assert strat["physique"] == "deep_remove_none"


def test_state_core_hook_mode_and_fields():
    from engine.archive.archive_hook import ArchiveDeltaContext

    hook = _delta_hook("state")
    assert set(hook.fields) == {"state", "gender", "address_ref", "self_ref"}
    base = dict(
        char={"name": "甲", "causal_anchors": {}, "sliders": {}},
        chapter=3, relevant_stages=[], prior=None, prior_appearances=[], call_llm=None,
    )
    rolling = hook.prompt_fragment(ArchiveDeltaContext(mode="rolling", **base))
    cold = hook.prompt_fragment(ArchiveDeltaContext(mode="cold_start", **base))
    assert rolling != cold
    assert "累积 delta" in cold or "推演" in cold


@pytest.mark.asyncio
async def test_run_state_delta_call_dispatches_parse():
    from engine.archive.archive_hook import ArchiveDeltaContext
    from engine.archive.state_delta_call import run_state_delta_call

    seen = {}

    async def _call(system, user, label):
        seen["system"] = system
        return {"stages": {"1": {"thought_process": {}, "delta": {
            "sliders": {}, "physique": {}, "state": {"psychology": "x"},
            "gender": "female", "address_ref": "夫君",
        }}}}

    ctx = ArchiveDeltaContext(
        char={"name": "甲", "causal_anchors": {}, "physique": {}, "sliders": {}},
        chapter=3, relevant_stages=[{"stage_num": 1, "location": "庭院", "archetype": ""}],
        mode="rolling", prior=None, prior_appearances=[], call_llm=_call,
    )
    parsed = await run_state_delta_call(ctx)
    assert "1" in parsed
    d = parsed["1"]["delta"]
    assert d["state"] == {"psychology": "x"}
    assert isinstance(d["sliders"], dict)
    assert "滑块档位" in seen["system"]


def test_enrich_hook_default_phase_and_empty():
    class _H(ArchiveEnrichHook):
        name = "x"

    h = _H()
    assert h.phase == ArchivePhase.ENRICH


@pytest.mark.asyncio
async def test_enrich_base_returns_empty():
    class _H(ArchiveEnrichHook):
        name = "x"

    async def _call(system, user, label):
        return {}

    ctx = ArchiveEnrichContext(
        char={"name": "甲"}, chapter=1, relevant_stages=[],
        resolved_by_stage={}, call_llm=_call,
    )
    assert await _H().enrich(ctx) == {}
