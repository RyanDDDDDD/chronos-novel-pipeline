from engine.setup_chat import skill_activation as sa


def test_strip_activation_for_display():
    header = sa._ACTIVATION_HEADER
    content = f"正常回复给用户。\n\n{header}\n\n你是剧情扩展引导员……（被复述的正文）"
    assert sa.strip_activation_for_display(content).strip() == "正常回复给用户。"
    assert sa.strip_activation_for_display("没有注入块的正文") == "没有注入块的正文"


def test_parse_slash_command_forms():
    assert sa.parse_slash_command("/foreshadowing") == "foreshadowing"
    assert sa.parse_slash_command("/x-y_z9 帮我梳理") == "x-y_z9"
    assert sa.parse_slash_command("  /padded  ") == "padded"
    assert sa.parse_slash_command("普通消息") is None
    assert sa.parse_slash_command("/中文名") is None
    assert sa.parse_slash_command("") is None
    assert sa.parse_slash_command("/") is None


def _idx_two():
    return [
        {"name": "explicit-one", "description": "", "kind": "", "source": "builtin"},
        {"name": "heuristic-one", "description": "", "kind": "", "source": "builtin"},
    ]


def test_slash_explicit_injects_skill(monkeypatch):
    monkeypatch.setattr(sa, "list_skill_index", lambda d: _idx_two())
    monkeypatch.setattr(sa, "load_skill_body", lambda n, d: f"BODY::{n}")
    monkeypatch.setattr(sa, "expand_skill_placeholders", lambda b, d: f"EXP::{b}")
    out = sa.build_skill_activations(
        [{"type": "human", "content": "/explicit-one 开始吧"}], ["/x"])
    assert out == ["EXP::BODY::explicit-one"]


def test_slash_unknown_name_returns_empty(monkeypatch):
    monkeypatch.setattr(sa, "list_skill_index", lambda d: _idx_two())
    monkeypatch.setattr(sa, "load_skill_body", lambda n, d: f"BODY::{n}")
    out = sa.build_skill_activations(
        [{"type": "human", "content": "/no-such-skill 写剧情"}], ["/x"])
    assert out == []
