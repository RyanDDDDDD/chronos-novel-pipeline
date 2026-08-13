from utils import config as cfg


def test_engine_port_default(monkeypatch):
    monkeypatch.delenv("CHRONOS_ENGINE_PORT", raising=False)
    assert cfg.engine_port({"server": {}}) == 8776


def test_engine_port_from_config(monkeypatch):
    monkeypatch.delenv("CHRONOS_ENGINE_PORT", raising=False)
    assert cfg.engine_port({"server": {"engine_port": 9001}}) == 9001


def test_engine_port_env_override(monkeypatch):
    monkeypatch.setenv("CHRONOS_ENGINE_PORT", "9999")
    assert cfg.engine_port() == 9999
