"""Programmatic Alembic runner used at Engine-open time (repositories/engine.py) and
by scripts/migrate_db.py. Legacy dbs (the 17 already-migrated novels + the registry)
have the tables but no alembic_version row -- those get stamped, never rebuilt."""
from __future__ import annotations

import os
import threading

import alembic.command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, pool

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_migrated_paths: set[str] = set()
_lock = threading.Lock()


def _cfg(ini_name: str, db_path: str) -> Config:
    cfg = Config(os.path.join(_ROOT, ini_name))
    sub_dir = "novel" if "novel" in ini_name else "registry"
    cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic", sub_dir))
    cfg.attributes["db"] = db_path
    cfg.cmd_opts = type("O", (), {"x": [f"db={db_path}"]})()  # feed -x
    return cfg


def _ensure(ini_name: str, db_path: str, sentinel_table: str) -> None:
    norm_path = os.path.abspath(db_path)
    with _lock:
        if norm_path in _migrated_paths and os.path.exists(norm_path):
            return
        os.makedirs(os.path.dirname(norm_path) or ".", exist_ok=True)
        temp_engine = create_engine(f"sqlite:///{norm_path}", poolclass=pool.NullPool)
        insp = inspect(temp_engine)
        names = set(insp.get_table_names())
        temp_engine.dispose()
        cfg = _cfg(ini_name, norm_path)
        if "alembic_version" in names:
            alembic_command.upgrade(cfg, "head")
        elif sentinel_table in names:
            alembic_command.stamp(cfg, "head")
        else:
            alembic_command.upgrade(cfg, "head")
        _migrated_paths.add(norm_path)


def ensure_novel_db_migrated(db_path: str) -> None:
    _ensure("alembic_novel.ini", db_path, "lore_characters")


def ensure_registry_migrated(db_path: str) -> None:
    _ensure("alembic_registry.ini", db_path, "novels")
