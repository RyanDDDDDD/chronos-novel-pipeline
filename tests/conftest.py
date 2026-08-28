"""Shared pytest fixtures for all test packages under tests/."""
import _testmon_inmemory
import pytest


def seed_registry_novel(
    novels_root,
    nid: str,
    name: str,
    *,
    active: bool = False,
    prose_style: dict | None = None,
) -> None:
    """Create physical novel dirs + registry row + default novel_settings doc."""
    from api.services import novels as nv
    from repositories.registry_store import get_registry_connection

    d = novels_root / nid
    (d / "lore").mkdir(parents=True, exist_ok=True)
    (d / "plot").mkdir(exist_ok=True)
    (d / "chapters").mkdir(exist_ok=True)
    conn = get_registry_connection()
    conn.execute(
        "INSERT OR REPLACE INTO novels (id, name, created_at, is_active) VALUES (?, ?, ?, ?)",
        (nid, name, "2020-01-01T00:00:00+00:00", 1 if active else 0),
    )
    conn.commit()
    if prose_style is not None:
        nv._write_novel_settings(str(nid), {"prose_style": prose_style})
    else:
        nv._write_default_novel_settings(str(nid))


@pytest.fixture(autouse=True)
def _reset_llm_singleton_caches():
    """Process-wide LLM singletons must not leak across tests."""
    from llm.factory import reset_cloud_llm_cache, reset_style_guard_llm_cache

    reset_cloud_llm_cache()
    reset_style_guard_llm_cache()
    yield
    reset_cloud_llm_cache()
    reset_style_guard_llm_cache()


@pytest.fixture(autouse=True)
def _instant_image_gen_gate(monkeypatch):
    """Zero every ImageGenGate sleep so portrait tests don't wait the real 3s interval /
    8-45s 429 backoff. Swaps the whole singleton -- _run_portrait_generation imports
    IMAGE_GEN_GATE locally on each call, so patching the module attr is enough."""
    from media.portrait import gate

    monkeypatch.setattr(
        gate,
        "IMAGE_GEN_GATE",
        gate.ImageGenGate(
            min_interval_s=0.0,
            rate_limit_backoff_s=(0.0, 0.0, 0.0),
            transient_backoff_s=0.0,
        ),
    )


def pytest_sessionstart(session):
    # testmon only attaches `testmon_data` to config when --testmon/--testmon-noselect
    # actually took effect (see testmon/pytest_testmon.py::pytest_configure) -- a plain
    # `pytest -q` run skips this entirely.
    if hasattr(session.config, "testmon_data"):
        _testmon_inmemory.verify_patch_took_effect(session.config.testmon_data)


def pytest_sessionfinish(session, exitstatus):
    _testmon_inmemory.flush_to_disk()
