"""Dashboard aggregation: Scan per-novel token_ledger doc → Each novel × subsystem × chapter + total."""
from __future__ import annotations

from repositories import registry_store

from api.services import novels as novels_svc
from api.services.token_ledger import load_ledger

_FIELDS = ("tokens_in", "tokens_out", "tokens_cached")


def novel_title(novel_id: str) -> str:
    """Novel title; cannot be obtained → use id."""
    return novels_svc.get_novel_name(novel_id)


def _cell(cell: dict) -> dict:
    tin = int(cell.get("tokens_in", 0))
    tout = int(cell.get("tokens_out", 0))
    tc = int(cell.get("tokens_cached", 0))
    return {"tokens_in": tin, "tokens_out": tout, "tokens_cached": tc}


def _zero() -> dict:
    return {"tokens_in": 0, "tokens_out": 0, "tokens_cached": 0}


def _add(acc: dict, cell: dict) -> None:
    for f in _FIELDS:
        acc[f] += cell[f]


def aggregate_token_stats() -> dict:
    novels_out: list[dict] = []
    grand = _zero()
    try:
        novel_ids = registry_store.visible_ids_sorted()
    except Exception:
        novel_ids = []
    for nid in novel_ids:
        ledger = load_ledger(nid)
        subsystems: dict[str, dict] = {}
        nov_total = _zero()
        for subsystem, cells in ledger.items():
            if not isinstance(cells, dict):
                continue
            by_chapter: dict[str, dict] = {}
            sub_total = _zero()
            for key, cell in cells.items():
                if not isinstance(cell, dict):
                    continue
                wc = _cell(cell)
                by_chapter[key] = wc
                _add(sub_total, wc)
            subsystems[subsystem] = {"by_chapter": by_chapter, "total": sub_total}
            _add(nov_total, sub_total)
        novels_out.append({
            "novel_id": nid, "title": novel_title(nid),
            "subsystems": subsystems, "total": nov_total,
        })
        _add(grand, nov_total)
    return {"novels": novels_out, "grand_total": grand}
