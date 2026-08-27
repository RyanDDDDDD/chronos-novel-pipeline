"""per-novel token ledger (covering semantics, atomic writes, foreign key preservation).

Shape: {subsystem: {key(chapter number/stage name): {tokens_in,tokens_out,tokens_cached,model}}}.
run starts reset_cell clears the cell → this time add_to_cell accumulates = "only the most recent one". all write read-modify-write,
Preserve other subsystems/chapters (follow the author_loop_skill_prefs foreign key preservation lesson). Statistics bypass: read and write failures are not thrown or downgraded."""
from __future__ import annotations

import os

from loguru import logger
from repositories.sqlite_store import SqliteStore
from utils.paths import active_novel_dir, active_novel_id

_DOC_KEY = "token_ledger"


def _store(novel_id: str | None = None) -> SqliteStore:
    return SqliteStore(novel_id or active_novel_id())


def ledger_path(novel_id: str | None = None) -> str:
    _ = novel_id
    return os.path.join(active_novel_dir(), "token_ledger.json")


def load_ledger(novel_id: str | None = None) -> dict:
    try:
        data = _store(novel_id).get_doc(_DOC_KEY, "")
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("[token-ledger] load_ledger 失败：{}", e)
        return {}


def _atomic_write(doc: dict, novel_id: str | None) -> None:
    _store(novel_id).save_doc(_DOC_KEY, "", doc)


def reset_cell(subsystem: str, key: str, *, novel_id: str | None = None) -> None:
    """
run starts by clearing the cell (override semantics). Failure → downgrade (warning)."""
    try:
        doc = load_ledger(novel_id)
        doc.setdefault(subsystem, {})[key] = {
            "tokens_in": 0, "tokens_out": 0, "tokens_cached": 0, "model": ""}
        _atomic_write(doc, novel_id)
    except Exception as e:
        logger.warning("[token-ledger] reset_cell 失败 {}/{}：{}", subsystem, key, e)


def add_to_cell(
    subsystem: str, key: str,
    tokens_in: int, tokens_out: int, tokens_cached: int, model: str,
    *, novel_id: str | None = None,
) -> dict:
    """Accumulate the cell and write it back atomically, returning the new value. Failure → Returns the input parameter increment without throwing (bypass)."""
    cell = {"tokens_in": tokens_in, "tokens_out": tokens_out,
            "tokens_cached": tokens_cached, "model": model}
    try:
        doc = load_ledger(novel_id)
        prev = (doc.get(subsystem, {}) or {}).get(key, {}) or {}
        cell = {
            "tokens_in": int(prev.get("tokens_in", 0)) + tokens_in,
            "tokens_out": int(prev.get("tokens_out", 0)) + tokens_out,
            "tokens_cached": int(prev.get("tokens_cached", 0)) + tokens_cached,
            "model": model or str(prev.get("model", "")),
        }
        doc.setdefault(subsystem, {})[key] = cell
        _atomic_write(doc, novel_id)
    except Exception as e:
        logger.warning("[token-ledger] add_to_cell 失败 {}/{}：{}", subsystem, key, e)
    return cell
