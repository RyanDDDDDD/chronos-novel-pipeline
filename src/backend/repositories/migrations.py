"""Programmatic Alembic runner used at Engine-open time (repositories/engine.py) and
by scripts/migrate_db.py.

Three db states to reconcile:
  * fresh (no tables)                    -> upgrade head (build everything)
  * already has alembic_version          -> upgrade head (normal path)
  * legacy: tables but no alembic_version -> stamp, never rebuild. The stamp point
    depends on how far the retired runtime ALTER hooks had gotten it: a novel db
    whose lore_characters still lacks the `version` column is stamped at 0001 and
    then upgraded (0002 adds the column); one that has it is stamped straight at
    head.
"""
from __future__ import annotations

import os
import threading

import alembic.command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, pool

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_migrated_paths: set[str] = set()
_lock = threading.Lock()

_NOVEL_PRE_VERSION_REVISION = "0001_initial_novel_schema"


def _cfg(ini_name: str, db_path: str) -> Config:
    cfg = Config(os.path.join(_ROOT, ini_name))
    sub_dir = "novel" if "novel" in ini_name else "registry"
    cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic", sub_dir))
    cfg.attributes["db"] = db_path
    cfg.cmd_opts = type("O", (), {"x": [f"db={db_path}"]})()  # feed -x to env.py
    return cfg


def _inspect(db_path: str) -> tuple[set[str], set[str]]:
    """Returns (table names, lore_characters column names) for the db at db_path."""
    engine = create_engine(f"sqlite:///{db_path}", poolclass=pool.NullPool)
    try:
        insp = inspect(engine)
        names = set(insp.get_table_names())
        lore_cols = (
            {c["name"] for c in insp.get_columns("lore_characters")}
            if "lore_characters" in names
            else set()
        )
        return names, lore_cols
    finally:
        engine.dispose()


def _run(cfg: Config, names: set[str], lore_cols: set[str], sentinel_table: str, is_novel: bool) -> None:
    if "alembic_version" in names:
        alembic_command.upgrade(cfg, "head")
    elif sentinel_table not in names:
        alembic_command.upgrade(cfg, "head")
    elif is_novel and "version" not in lore_cols:
        # Legacy scaffold that never got the runtime version-column ALTER.
        alembic_command.stamp(cfg, _NOVEL_PRE_VERSION_REVISION)
        alembic_command.upgrade(cfg, "head")
    else:
        alembic_command.stamp(cfg, "head")


def _ensure(ini_name: str, db_path: str, sentinel_table: str, is_novel: bool) -> None:
    norm_path = os.path.abspath(db_path)
    with _lock:
        if norm_path in _migrated_paths and os.path.exists(norm_path):
            return
        os.makedirs(os.path.dirname(norm_path) or ".", exist_ok=True)
        names, lore_cols = _inspect(norm_path)
        _run(_cfg(ini_name, norm_path), names, lore_cols, sentinel_table, is_novel)
        _migrated_paths.add(norm_path)


def ensure_novel_db_migrated(db_path: str) -> None:
    _ensure("alembic_novel.ini", db_path, "lore_characters", is_novel=True)


def ensure_registry_migrated(db_path: str) -> None:
    _ensure("alembic_registry.ini", db_path, "novels", is_novel=False)
