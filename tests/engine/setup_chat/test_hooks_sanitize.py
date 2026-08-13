from engine.setup_chat.hooks import make_post_model_hook
from langchain_core.messages import AIMessage, HumanMessage


def test_post_hook_strips_decision_echo(tmp_path):
    from engine.setup_chat.memory import save_memory

    novel_dir = tmp_path / "default"
    persist = novel_dir / "setup_chat"
    persist.mkdir(parents=True)
    save_memory(str(persist), {"decisions": ["星黏液简化为粘液/史莱姆"]})
    hook = make_post_model_hook(lambda: str(persist))
    ai = AIMessage(
        content="星黏液简化为粘液/史莱姆\n\n好的，已记录。",
        id="a1",
        additional_kwargs={"reasoning_content": "internal reasoning"},
    )
    out = hook({"messages": [HumanMessage(content="hi"), ai]})
    msgs = out.get("messages") or []
    assert len(msgs) == 2
    fixed = msgs[-1]
    assert getattr(fixed, "content", "") == "好的，已记录。"
    assert fixed.additional_kwargs.get("reasoning_content") == "internal reasoning"
