"""Repository-layer test fixtures: in-memory SQLite engines built straight from
metadata (no Alembic), with repositories.engine pointed at them."""
from __future__ import annotations

import pytest
import repositories.engine as engine_mod
from sqlmodel import SQLModel, create_engine


@pytest.fixture
def novel_engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(engine_mod, "_engines", {})
    monkeypatch.setattr(engine_mod, "engine_for_novel", lambda nid=None: eng)
    monkeypatch.setattr(engine_mod, "_archive_caches", {})
    return eng
