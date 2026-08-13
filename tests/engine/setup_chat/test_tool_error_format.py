"""Cleaning of ToolNode verification error reporting: only field-level errors are returned, and kwargs full-text dumps are never returned."""
from engine.setup_chat.agent import clean_tool_error
from pydantic import BaseModel, ValidationError


def _make_validation_error() -> ValidationError:
    class _M(BaseModel):
        roles: dict[str, int]

    try:
        _M.model_validate({"roles": {"外来者": "not-an-int"}})
    except ValidationError as e:
        return e
    raise AssertionError("应当抛出 ValidationError")


def test_clean_tool_error_strips_kwargs_dump():
    src = _make_validation_error()
    #Simulate the shape of langgraph ToolInvocationError (tool_name + source=ValidationError)
    fake = type("E", (), {"tool_name": "construct_character_schema", "source": src})()
    out = clean_tool_error(fake)

    assert "construct_character_schema" in out  #Click which tool it is
    assert "roles" in out  #Give error field location
    assert "with kwargs" not in out  #No more giant kwargs templates for langgraph
    assert "未执行" in out  #Clearly not placed
    assert "重新调用" in out  #Guide current round correction and reissue


def test_clean_tool_error_generic_exception_is_concise():
    out = clean_tool_error(ValueError("boom"))
    assert "boom" in out
    assert "ValueError" in out
    #The bottom of the pocket should also be short and not thrown (to prevent the whole wheel from collapsing)
    assert len(out) < 200
