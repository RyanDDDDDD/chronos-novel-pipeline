"""API: per-novel sandbox dialogue draft turn-count reading and writing."""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import seed_registry_novel


@pytest.fixture
def turn_count_api_client(tmp_path, monkeypatch):
    import api.hub as hub
    from api.services.message_hub import MessageHub

    novels = tmp_path / "novels"
    novels.mkdir(exist_ok=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels))
    seed_registry_novel(novels, "default", "默认", active=True)

    hub.HUB = MessageHub()
    return TestClient(hub.app)


def test_get_sandbox_dialogue_turn_count_defaults_to_null(turn_count_api_client):
    r = turn_count_api_client.get("/api/novels/default/sandbox-dialogue-turn-count")
    assert r.status_code == 200
    assert r.json() == {"turn_count": None}


def test_set_sandbox_dialogue_turn_count_roundtrip(turn_count_api_client):
    import api.services.novels as nv

    r = turn_count_api_client.put(
        "/api/novels/default/sandbox-dialogue-turn-count", json={"turn_count": 5},
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    r2 = turn_count_api_client.get("/api/novels/default/sandbox-dialogue-turn-count")
    assert r2.json() == {"turn_count": 5}
    assert nv.get_sandbox_dialogue_turn_count("default") == 5


def test_set_sandbox_dialogue_turn_count_null_clears_to_auto(turn_count_api_client):
    turn_count_api_client.put("/api/novels/default/sandbox-dialogue-turn-count", json={"turn_count": 5})
    r = turn_count_api_client.put(
        "/api/novels/default/sandbox-dialogue-turn-count", json={"turn_count": None},
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    r2 = turn_count_api_client.get("/api/novels/default/sandbox-dialogue-turn-count")
    assert r2.json() == {"turn_count": None}


def test_set_sandbox_dialogue_turn_count_zero_rejected(turn_count_api_client):
    r = turn_count_api_client.put(
        "/api/novels/default/sandbox-dialogue-turn-count", json={"turn_count": 0},
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_set_sandbox_dialogue_turn_count_too_large_rejected(turn_count_api_client):
    r = turn_count_api_client.put(
        "/api/novels/default/sandbox-dialogue-turn-count", json={"turn_count": 21},
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_set_sandbox_dialogue_turn_count_non_integer_rejected(turn_count_api_client):
    r = turn_count_api_client.put(
        "/api/novels/default/sandbox-dialogue-turn-count", json={"turn_count": "五"},
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_set_sandbox_dialogue_turn_count_unknown_novel_rejected(turn_count_api_client):
    r = turn_count_api_client.put(
        "/api/novels/nope/sandbox-dialogue-turn-count", json={"turn_count": 5},
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False
