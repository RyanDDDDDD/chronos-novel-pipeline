"""Tests for cold start + stage-level character_timeline writing."""
import pytest


def _patch_rubrics(monkeypatch, role_keyed: dict) -> None:
    role_axes = next(iter(role_keyed.values()))
    flat = {
        ax: (spec.get("levels") if isinstance(spec, dict) else spec)
        for ax, spec in role_axes.items()
    }
    monkeypatch.setattr("engine.archive.sliders.character_rubrics", lambda _n: flat)


def test_build_coldstart_message_uses_anchors_init_and_outline(monkeypatch):
    from engine.archive.archive_hook import ArchiveDeltaContext
    from engine.archive.state_delta_call import _build_system, _build_user

    rubrics = {"甲": {
        "投入": {"direction": -1, "levels": {"5": "意志完整"}},
        "依恋": {"direction": 1, "levels": {"0": "毫无"}},
    }}
    _patch_rubrics(monkeypatch, rubrics)

    char = {"name": "女主丙", "role": "甲",
            "causal_anchors": {"起点": "傲骨", "执念": "高贵", "渴望": "母犬"},
            "sliders": {"投入": 5, "依恋": 0}}
    appearances = [{"chapter": 1, "description": "初遇受挫"},
                   {"chapter": 3, "description": "二度交锋"}]
    ctx = ArchiveDeltaContext(
        char=char, chapter=6, relevant_stages=[], mode="cold_start",
        prior=None, prior_appearances=appearances, call_llm=None,
    )
    msg = _build_system(ctx) + _build_user(ctx)
    assert "傲骨" in msg and "母犬" in msg
    assert "初遇受挫" in msg and "二度交锋" in msg
    assert "意志完整" in msg and "毫无" in msg
    assert "第 6 章" in msg or "本章开局" in msg
    assert "delta" in msg


@pytest.mark.asyncio
async def test_cold_start_prior_invokes_llm_and_writes_timeline(monkeypatch):
    import context.character_timeline as ctl

    from context.character_resolver import resolve_from
    from engine.archive.archive_hook import ArchiveDeltaContext
    from engine.archive.state_delta_call import run_state_delta_call
    from repo_test_helpers import seed_lore, seed_plot

    rubrics = {"甲": {
        "投入": {"direction": -1, "levels": {"2": "理智旁观"}},
        "依恋": {"direction": 1, "levels": {"3": "渴求"}},
    }}
    _patch_rubrics(monkeypatch, rubrics)

    char = {"name": "女主丙", "role": "甲",
        "causal_anchors": {"起点": "w", "执念": "l", "渴望": "n"},
        "sliders": {"投入": 5, "依恋": 0}}
    payload = {"delta": {"sliders": {"投入": "理智旁观", "依恋": "渴求"},
                         "state": {"physiology": "p", "psychology": "q"}}}

    async def fake_call(system, user, label):
        return payload

    ctx = ArchiveDeltaContext(
        char=char, chapter=6, relevant_stages=[], mode="cold_start",
        prior=None, prior_appearances=[{"chapter": 1, "description": "受挫"}],
        call_llm=fake_call,
    )
    parsed = await run_state_delta_call(ctx)
    delta = parsed["1"]["delta"]
    seed_lore([{"name": "女主丙", "role": "甲"}])
    seed_plot([{"chapter": 5}])
    ctl.append_stage("女主丙", 5, 1, delta)
    prior = resolve_from(char, ctl.load_timeline("女主丙")["snapshots"], 5, 1)
    assert prior["sliders"] == {"投入": 2, "依恋": 3}
    assert prior["state"]["physiology"] == "p"
    snaps = ctl.load_timeline("女主丙")["snapshots"]
    assert len(snaps) == 1
    assert snaps[0]["chapter"] == 5 and snaps[0]["stage"] == 1


@pytest.mark.asyncio
async def test_cold_start_prior_none_when_no_history(monkeypatch, tmp_path):
    from engine.archive.archive_hook import ArchiveDeltaContext

    char = {"name": "新人", "causal_anchors": {"stance": "submissive"}}
    ctx = ArchiveDeltaContext(
        char=char, chapter=6, relevant_stages=[], mode="cold_start",
        prior=None, prior_appearances=[], call_llm=None,
    )
    assert ctx.prior_appearances == []
