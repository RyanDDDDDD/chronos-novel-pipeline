from tests.conftest import seed_registry_novel

import api.services.token_stats as ts
from api.services import token_ledger as tl


def test_aggregate_across_novels(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    seed_registry_novel(tmp_path, "default", "default")
    seed_registry_novel(tmp_path, "novelB", "novelB")
    tl.add_to_cell(
        "author_loop", "6", 100, 40, 0, "m", novel_id="default",
    )
    tl.add_to_cell(
        "archive", "6", 10, 5, 0, "m", novel_id="default",
    )
    tl.add_to_cell(
        "setup", "cast", 7, 3, 0, "m", novel_id="novelB",
    )

    out = ts.aggregate_token_stats()
    nv = {n["novel_id"]: n for n in out["novels"]}
    assert nv["default"]["subsystems"]["author_loop"]["by_chapter"]["6"]["tokens_in"] == 100
    assert nv["default"]["subsystems"]["author_loop"]["total"]["tokens_out"] == 40
    assert out["grand_total"]["tokens_in"] == 117


def test_missing_ledger_novel_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    seed_registry_novel(tmp_path, "empty", "empty")
    out = ts.aggregate_token_stats()
    assert out["novels"][0]["subsystems"] == {}
    assert out["grand_total"]["tokens_in"] == 0
