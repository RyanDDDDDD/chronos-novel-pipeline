"""Agent Package structure verification (docs/AGENT_PACKAGE.md §11).

Note: Exclude "whether an agent appears in the live manifest" - that is a node existence assertion (violating free orchestration)
Article 11), and is sensitive to the active pipeline (switching to the streamlined pipeline results in false positives). Only test the structure verification logic itself**
(Complete prompt files, EXAMPLE name deprecation detection) - Use the stub manifest, which has nothing to do with the specific arrangement."""
from engine.validator.agent_package_check import check_manifest_agent_packages


def test_legacy_example_md_rejected(tmp_path):
    manifest = {
        "nodes": {
            "start": {"type": "start"},
            "n": {"agent": "seg", "inputs": ["start"]},
        }
    }
    pkg = tmp_path / "seg"
    pkg.mkdir()
    (pkg / "segment_guidance.md").write_text("# x", encoding="utf-8")
    (pkg / "EXAMPLE.md").write_text("legacy", encoding="utf-8")
    (pkg / "segment_guidance_EXAMPLE.md").write_text("ok", encoding="utf-8")
    (pkg / "agent.meta.json").write_text(
        '{"package":"seg","roles":["segment_guidance"],"nodes":["n"]}',
        encoding="utf-8",
    )
    (pkg / "hook.py").write_text(
        "from engine.execution.agent_hook import AgentHook\n"
        "class Hook(AgentHook):\n"
        "    default_role = 'segment_guidance'\n",
        encoding="utf-8",
    )
    errors = check_manifest_agent_packages(manifest, tmp_path)
    assert any("EXAMPLE.md" in e and "废弃" in e for e in errors)


def test_missing_prompt_detected(tmp_path):
    manifest = {
        "nodes": {
            "start": {"type": "start"},
            "only": {"agent": "ghost_pkg", "inputs": ["start"]},
        }
    }
    pkg = tmp_path / "ghost_pkg"
    pkg.mkdir()
    (pkg / "hook.py").write_text(
        "from engine.execution.agent_hook import AgentHook\n"
        "class Hook(AgentHook):\n"
        "    default_role = 'ghost_role'\n",
        encoding="utf-8",
    )
    errors = check_manifest_agent_packages(manifest, tmp_path)
    assert any("ghost_role.md" in e for e in errors)
