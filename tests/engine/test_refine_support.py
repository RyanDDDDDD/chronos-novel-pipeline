"""refine_analysis existence = whether REFINE is supported."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))

from llm.prompt_manager import PromptManager


def test_has_refine_analysis_tmp_dir(tmp_path):
    agent_dir = tmp_path / "fake_agent"
    agent_dir.mkdir()
    assert PromptManager.has_refine_analysis("fake_agent", None, str(tmp_path)) is False
    (agent_dir / "refine_analysis.md").write_text("x", encoding="utf-8")
    assert PromptManager.has_refine_analysis("fake_agent", None, str(tmp_path)) is True
    (agent_dir / "role_x_refine_analysis.md").write_text("y", encoding="utf-8")
    assert PromptManager.has_refine_analysis("fake_agent", "role_x", str(tmp_path)) is True
