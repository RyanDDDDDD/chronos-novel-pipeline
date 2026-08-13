import asyncio

import api.services.message_hub as mh_mod
import pytest
from api.services.message_hub import MessageHub
from engine.story_sandbox.derivation_retry import DerivationValidationError, SandboxErrorCode
from engine.story_sandbox.state import LEGACY_BRANCH_ID, SandboxStepType


@pytest.fixture(autouse=True)
def _isolated_story_sandbox_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "utils.paths.story_sandbox_checkpoint_path", lambda: str(tmp_path / "sandbox.sqlite"),
    )
    yield
    from engine.story_sandbox.graph import close_checkpointer

    asyncio.run(close_checkpointer())


@pytest.fixture(autouse=True)
def _isolated_sandbox_llm_routing(monkeypatch):
    import engine.modes.author_loop_skill_prefs as prefs_mod

    monkeypatch.setattr(
        prefs_mod, "load_dialogue_prefs",
        lambda: {
            "target_words": prefs_mod.DEFAULT_TARGET_WORDS,
            "disabled_buildtime_review_hooks": [], "disabled_runtime_review_hooks": [],
            "llm_params": {}, "sandbox_llm_params": {},
        },
    )


def _cache_key(hub: MessageHub, chapter: int, branch_id: str = LEGACY_BRANCH_ID) -> tuple[str, int, str]:
    return (mh_mod.active_novel_id(), chapter, branch_id)


async def _await_hub_task(hub: MessageHub) -> None:
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t


def _fake_cloud_llm(prose_astream_calls: list[int] | None = None, prose_text: str = "定稿正文"):
    from langchain_core.messages import AIMessage

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content
            self.usage_metadata = {
                "input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                "input_token_details": {},
            }

    class _FakeLLM:
        model = "test-model"

        def bind(self, **kwargs):
            return self

        async def astream(self, messages, stream_usage=False):
            if prose_astream_calls is not None:
                prose_astream_calls.append(1)
            yield _Chunk(prose_text)

        async def ainvoke(self, messages):
            return AIMessage(content="{}")

    return _FakeLLM()


@pytest.mark.asyncio
async def test_retry_derive_reuses_cached_prose_without_second_write_turn_call(monkeypatch):
    prose_astream_calls: list[int] = []
    run_invocations = {"n": 0}
    cached_final_text = "定稿正文"

    async def fake_run_turn(
        novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene,
        call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char,
        guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate,
        guard_text_suggest, submitted_directions=None, call_llm_identify=None,
        call_llm_dialogue_draft=None, branch_id=None,
    ):
        run_invocations["n"] += 1
        prose = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": prose, "active_cast": []}
        if run_invocations["n"] == 1:
            raise DerivationValidationError(SandboxErrorCode.SCENE_DERIVE_FAILED, "不是JSON")
        yield {
            "type": SandboxStepType.STATE,
            "states": {"甲": {"psychology": "平静", "posture": "", "clothing": ""}},
            "scene_state": {"description": "书房"},
            "active_cast": [],
        }
        yield {"type": SandboxStepType.SUGGESTIONS, "options": ["建议A"], "round_id": "r1"}

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr(
        "llm.factory.get_cloud_llm",
        lambda: _fake_cloud_llm(prose_astream_calls, cached_final_text),
    )
    hub = MessageHub()
    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续", branch_id="b1")
    await _await_hub_task(hub)
    assert hub._story_sandbox_derive_retry_cache[_cache_key(hub, 1, "b1")]["final_text"] == cached_final_text
    assert len(prose_astream_calls) == 1

    await hub.retry_story_sandbox_derive(1, branch_id="b1")
    await _await_hub_task(hub)

    assert len(prose_astream_calls) == 1
    assert run_invocations["n"] == 2
    assert hub._story_sandbox_derive_retry_cache.get(_cache_key(hub, 1, "b1")) is None


@pytest.mark.asyncio
async def test_retry_derive_raises_when_no_cache():
    hub = MessageHub()
    with pytest.raises(RuntimeError, match="没有可重试"):
        await hub.retry_story_sandbox_derive(1, branch_id="b1")


@pytest.mark.asyncio
async def test_retry_derive_keeps_cache_when_retry_fails_again(monkeypatch):
    run_invocations = {"n": 0}

    async def fake_run_turn(
        novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene,
        call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char,
        guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate,
        guard_text_suggest, submitted_directions=None, call_llm_identify=None,
        call_llm_dialogue_draft=None, branch_id=None,
    ):
        run_invocations["n"] += 1
        prose = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": prose or "定稿正文", "active_cast": []}
        raise DerivationValidationError(SandboxErrorCode.SCENE_DERIVE_FAILED, "不是JSON")

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _fake_cloud_llm())
    hub = MessageHub()
    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续", branch_id="b1")
    await _await_hub_task(hub)
    key = _cache_key(hub, 1, "b1")
    assert key in hub._story_sandbox_derive_retry_cache

    await hub.retry_story_sandbox_derive(1, branch_id="b1")
    await _await_hub_task(hub)
    assert key in hub._story_sandbox_derive_retry_cache
    assert run_invocations["n"] == 2

    await hub.retry_story_sandbox_derive(1, branch_id="b1")
    await _await_hub_task(hub)
    assert key in hub._story_sandbox_derive_retry_cache
    assert run_invocations["n"] == 3


@pytest.mark.asyncio
async def test_retry_derive_clears_cache_after_success(monkeypatch):
    run_invocations = {"n": 0}

    async def fake_run_turn(
        novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene,
        call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char,
        guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate,
        guard_text_suggest, submitted_directions=None, call_llm_identify=None,
        call_llm_dialogue_draft=None, branch_id=None,
    ):
        run_invocations["n"] += 1
        if run_invocations["n"] == 1:
            prose = await write_turn("system", "packet")
            yield {"type": SandboxStepType.PROSE, "text": prose, "active_cast": []}
            raise DerivationValidationError(SandboxErrorCode.SCENE_DERIVE_FAILED, "不是JSON")
        prose = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": prose, "active_cast": []}
        yield {"type": SandboxStepType.STATE, "states": {}, "scene_state": {}}
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _fake_cloud_llm())
    hub = MessageHub()
    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续", branch_id="b1")
    await _await_hub_task(hub)
    key = _cache_key(hub, 1, "b1")
    assert key in hub._story_sandbox_derive_retry_cache

    await hub.retry_story_sandbox_derive(1, branch_id="b1")
    await _await_hub_task(hub)
    assert hub._story_sandbox_derive_retry_cache.get(key) is None

    with pytest.raises(RuntimeError, match="没有可重试"):
        await hub.retry_story_sandbox_derive(1, branch_id="b1")


@pytest.mark.asyncio
async def test_new_turn_clears_stale_derive_retry_cache(monkeypatch):
    run_invocations = {"n": 0}

    async def fake_run_turn(
        novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene,
        call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char,
        guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate,
        guard_text_suggest, submitted_directions=None, call_llm_identify=None,
        call_llm_dialogue_draft=None, branch_id=None,
    ):
        run_invocations["n"] += 1
        if run_invocations["n"] == 1:
            yield {"type": SandboxStepType.PROSE, "text": "旧正文", "active_cast": []}
            raise DerivationValidationError(SandboxErrorCode.SCENE_DERIVE_FAILED, "不是JSON")
        yield {"type": SandboxStepType.PROSE, "text": "新正文", "active_cast": []}
        yield {"type": SandboxStepType.STATE, "states": {}, "scene_state": {}}
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _fake_cloud_llm())
    hub = MessageHub()
    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "第一次", branch_id="b1")
    await _await_hub_task(hub)
    key = _cache_key(hub, 1, "b1")
    stale = hub._story_sandbox_derive_retry_cache[key]
    assert stale["instruction"] == "第一次"

    await hub.start_story_sandbox_turn(1, "第二次", branch_id="b1")
    await _await_hub_task(hub)
    assert hub._story_sandbox_derive_retry_cache.get(key) is None

    with pytest.raises(RuntimeError, match="没有可重试"):
        await hub.retry_story_sandbox_derive(1, branch_id="b1")


def test_story_sandbox_retry_derive_endpoint_rejects_missing_branch_id():
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.post("/api/story-sandbox/retry-derive", json={"chapter": 1})
    assert res.status_code == 400


def test_story_sandbox_retry_derive_endpoint_returns_409_on_runtime_error(monkeypatch):
    from api import routes
    from api.hub import app
    from fastapi.testclient import TestClient

    async def fake_retry(chapter, branch_id=None):
        raise RuntimeError("没有可重试的推演失败记录，请重新输入指令")

    monkeypatch.setattr(routes._hub_instance(), "retry_story_sandbox_derive", fake_retry)
    client = TestClient(app)
    res = client.post("/api/story-sandbox/retry-derive", json={"chapter": 1, "branch_id": "b1"})
    assert res.status_code == 409
    assert "没有可重试" in res.json()["error"]


def test_story_sandbox_retry_derive_endpoint_starts_retry(monkeypatch):
    from api import routes
    from api.hub import app
    from fastapi.testclient import TestClient

    calls = []

    async def fake_retry(chapter, branch_id=None):
        calls.append((chapter, branch_id))

    monkeypatch.setattr(routes._hub_instance(), "retry_story_sandbox_derive", fake_retry)
    client = TestClient(app)
    res = client.post("/api/story-sandbox/retry-derive", json={"chapter": 1, "branch_id": "b1"})
    assert res.status_code == 200
    assert res.json() == {"ok": True, "status": "running"}
    assert calls == [(1, "b1")]


def test_story_sandbox_profile_mutate_rewrite_endpoint_allows_empty_feedback(monkeypatch):
    from api import routes
    from api.hub import app
    from fastapi.testclient import TestClient

    calls = []

    async def fake_rewrite(chapter, feedback, branch_id=None):
        calls.append((chapter, feedback, branch_id))

    monkeypatch.setattr(routes._hub_instance(), "rewrite_story_sandbox_profile_mutation", fake_rewrite)
    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/profile-mutate/rewrite",
        json={"chapter": 1, "branch_id": "b1", "feedback": ""},
    )
    assert res.status_code == 200
    assert calls == [(1, "", "b1")]


def test_story_sandbox_profile_mutate_rewrite_endpoint_starts_rewrite(monkeypatch):
    from api import routes
    from api.hub import app
    from fastapi.testclient import TestClient

    calls = []

    async def fake_rewrite(chapter, feedback, branch_id=None):
        calls.append((chapter, feedback, branch_id))

    monkeypatch.setattr(routes._hub_instance(), "rewrite_story_sandbox_profile_mutation", fake_rewrite)
    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/profile-mutate/rewrite",
        json={"chapter": 1, "branch_id": "b1", "feedback": "改为恶魔"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True, "status": "running"}
    assert calls == [(1, "改为恶魔", "b1")]
