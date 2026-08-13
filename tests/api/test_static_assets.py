from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_register_static_serves_index_from_dist_dir(monkeypatch) -> None:
    # Import lazily so we can monkeypatch the module-level dist_dir symbol.
    import api.routes as routes

    with TemporaryDirectory() as td:
        dist = Path(td)
        (dist / "assets").mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("<!doctype html><div id='root'></div>", encoding="utf-8")
        (dist / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
        (dist / "icons.svg").write_text("<svg></svg>", encoding="utf-8")

        monkeypatch.setattr(routes, "dist_dir", lambda: dist)

        app = FastAPI()
        routes.register_static(app)

        client = TestClient(app)
        r = client.get("/")
        assert r.status_code == 200
        assert "id='root'" in r.text

