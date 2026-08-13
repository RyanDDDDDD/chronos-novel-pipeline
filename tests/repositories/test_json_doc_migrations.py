"""Round-trip tests for JSON → sqlite document migrations."""
import pytest
from api.services import token_ledger
from engine.setup_chat import memory, session_record


@pytest.fixture
def novel_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    nid = "test-novel"
    root = tmp_path / nid
    (root / "setup_chat").mkdir(parents=True)
    (root / "session").mkdir()
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", nid)
    return nid, str(root / "setup_chat"), str(root / "session")


def test_token_ledger_roundtrip(novel_env):
    nid, _, _ = novel_env
    token_ledger.add_to_cell("author_loop", "1", 100, 50, 10, "model-x", novel_id=nid)
    ledger = token_ledger.load_ledger(nid)
    assert ledger["author_loop"]["1"]["tokens_in"] == 100


def test_setup_chat_memory_roundtrip(novel_env):
    _, persist_dir, _ = novel_env
    decision = {
        "id": "d1", "domain": "world", "text": "用户定了 A",
        "status": "active", "alert": None, "ts": 1000.0,
    }
    memory.save_memory(persist_dir, {"decisions": [decision]})
    loaded = memory.load_memory(persist_dir)
    assert loaded["decisions"] == [decision]


def test_session_messages_roundtrip(novel_env):
    _, _, session_dir = novel_env
    rec = session_record.append_user(session_dir, "hello")
    messages = session_record.load_messages(session_dir)
    assert len(messages) == 1
    assert messages[0]["content"] == "hello"
    assert messages[0]["id"] == rec["id"]
