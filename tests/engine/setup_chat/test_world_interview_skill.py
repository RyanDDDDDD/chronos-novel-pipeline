from engine.setup_chat import skills
from utils.paths import SETUP_CHAT_SKILLS_DIR


def test_world_interview_registered_in_real_dir():
    names = [s["name"] for s in skills.list_skill_index([SETUP_CHAT_SKILLS_DIR])]
    assert "world-interview" in names
    desc = next(
        s["description"]
        for s in skills.list_skill_index([SETUP_CHAT_SKILLS_DIR])
        if s["name"] == "world-interview"
    )
    assert desc  #description is not empty, used as trigger prompt


def test_world_interview_body_covers_seven_dimensions():
    body = skills.load_skill_body("world-interview", [SETUP_CHAT_SKILLS_DIR])
    assert body is not None
    for field in ("core_themes", "tone", "power_system",
                  "background", "factions", "geography", "races"):
        assert field in body, f"缺维度 {field}"
    #Global depth rules present
    assert "不深挖支线" in body
    #The writing steps are guided (conceptual, no specific common tool names - see agent-prompt-isolation)
    assert "落字成档" in body
    assert "construct_world" not in body
    assert "set_world_background" in body or "add_world_" in body
