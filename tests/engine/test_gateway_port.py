import asyncio

from api.services.gateway import Gateway
from api.services.gateway_port import GatewayRole, current_role, make_gateway


def test_role_defaults_to_combined(monkeypatch):
    monkeypatch.delenv("CHRONOS_ROLE", raising=False)
    assert current_role() == GatewayRole.COMBINED


def test_role_reads_env(monkeypatch):
    monkeypatch.setenv("CHRONOS_ROLE", "engine")
    assert current_role() == GatewayRole.ENGINE


def test_role_invalid_falls_back_to_combined(monkeypatch):
    monkeypatch.setenv("CHRONOS_ROLE", "bogus")
    assert current_role() == GatewayRole.COMBINED


def test_make_gateway_combined_returns_inproc(monkeypatch):
    monkeypatch.delenv("CHRONOS_ROLE", raising=False)
    gw = make_gateway()
    assert isinstance(gw, Gateway)


def test_inproc_gateway_has_lifecycle_noop():
    """协议要求 start/close 存在；inproc 为 no-op（可 await，不抛）。"""
    gw = Gateway()
    asyncio.run(gw.start())
    asyncio.run(gw.close())
