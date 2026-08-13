"""Structured storage layer: per-novel JSON file IO + archive memory cache + life cycle.

Absorb the original LoreIndexer / PlotIndexer / _archive_cache, and centralize the cache and invalidation.
When the novel is cut, reset() is called, and when the plot is placed, refresh_plot() is called.

For scripts/migrate_json_to_sqlite.py only: reads legacy JSON source data for migration; no longer
a runtime backend for any Repository."""
from __future__ import annotations

import json
import os
from typing import Any, cast

from utils.paths import (
    get_character_archive_dir,
    lore_library_path,
    plot_library_path,
)


class JsonStore:
    def __init__(self) -> None:
        self._lore: dict[str, dict] = {}        #name → role dict (including extensions merge), for get/list
        self._lore_raw: list[dict] = []         #lore file original array (conformal: including name missing items, original order)
        self._plot: dict[str, dict] = {}        #Chapter N → chapter dict
        self._plot_raw: list[dict] = []         #plot file original array (conformal + original order)
        self._archive_cache: dict[str, dict] = {}
        self._docs: dict[str, Any] = {}

    #---- life cycle ----
    def scan(self) -> None:
        """
Full scan lore + plot during startup (also used for rescan after cache invalidation)."""
        self._scan_lore()
        self._scan_plot()

    def reset(self) -> None:
        """Cut the novel: Rebuild according to the new active path, and clear the archive + document cache."""
        self._archive_cache.clear()
        self._docs.clear()
        self.scan()

    def refresh_plot(self) -> None:
        """
plot_library Rescan after placing the order."""
        self._scan_plot()

    def _scan_lore(self) -> None:
        self._lore = {}
        self._lore_raw = []
        path = lore_library_path()
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        chars = data["characters"] if isinstance(data, dict) and "characters" in data else data
        self._lore_raw = list(chars) if isinstance(chars, list) else []
        for cd in chars:
            name = cd.get("name")
            if name:
                self._lore[name] = dict(cd)
                self._lore[name].setdefault("extensions", {})
        story_cfg = os.path.join(os.path.dirname(path), "story_character_config.json")
        if os.path.exists(story_cfg):
            with open(story_cfg, encoding="utf-8") as f:
                cfg = json.load(f)
            for name, ext in cfg.items():
                if name in self._lore:
                    self._lore[name]["extensions"].update(ext)

    def _scan_plot(self) -> None:
        self._plot = {}
        self._plot_raw = []
        path = plot_library_path()
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            self._plot_raw = list(data)
            for p in data:
                ch = p.get("chapter")
                if ch is not None:
                    self._plot[f"第{ch}章"] = p
        elif isinstance(data, dict):
            self._plot = data
            self._plot_raw = list(data.values())

    #---- Atomic write + universal document write-through ----
    @staticmethod
    def _atomic_write_json(path: str, data: object) -> None:
        """Atomic write: tmp + os.replace to avoid half-written files (no fragments left after disk crash). If there are old files, the backup will be .bak."""
        import tempfile
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    old = f.read()
                with open(path + ".bak", "w", encoding="utf-8") as f:
                    f.write(old)
            except Exception:
                pass
        fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def get_doc(self, key: str, path: str) -> Any | None:
        """
The entire document: cache priority, miss read disk into cache; file does not exist → None."""
        if key in self._docs:
            return self._docs[key]
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._docs[key] = data
        return data

    def save_doc(self, key: str, path: str, data: Any) -> None:
        """Write-through: atomic write to disk + update cache (read cache is always a disk image)."""
        self._atomic_write_json(path, data)
        self._docs[key] = data

    # ---- lore ----
    def get_lore(self, name: str) -> dict | None:
        return self._lore.get(name)

    def list_lore(self) -> list[dict]:
        """
name-indexed role (including extensions merging); used for entity building/upsert. The missing name item is not included."""
        return list(self._lore.values())

    def list_lore_raw(self) -> list[dict]:
        """The original array of the lore file (shape-preserving and order-preserving, including the missing name item); transparent transmission for display."""
        return list(self._lore_raw)

    def save_lore(self, chars: list[dict], path: str | None = None) -> None:
        """
Whole database replacement write-through: write disk + rescan lore cache (including story_character_config merge)."""
        p = path if path is not None else lore_library_path()
        self._atomic_write_json(p, chars)
        self._scan_lore()

    # ---- plot ----
    def get_outline(self, chapter: int) -> dict | None:
        return self._plot.get(f"第{chapter}章")

    def list_plot(self) -> list[dict]:
        """Return all plot entries sorted by chapter number value (for upsert enumeration to remove duplicates)."""
        return sorted(self._plot.values(), key=lambda p: int(p.get("chapter", 0)))

    def list_plot_raw(self) -> list[dict]:
        """
The original array of the plot file (shape-preserving and order-preserving); transparent transmission for display."""
        return list(self._plot_raw)

    def save_plot(self, chapters: list[dict] | dict, path: str | None = None) -> None:
        """Whole database replacement write-through: write to disk + rescan plot cache."""
        p = path if path is not None else plot_library_path()
        self._atomic_write_json(p, chapters)
        self._scan_plot()

    #---- archive (caching takes precedence over touch disk) ----
    def put_archive(self, name: str, chapter: int, data: dict) -> None:
        """
Only the memory cache is updated (transitional retention); producers should use save_archive writethrough instead."""
        self._archive_cache[f"{name}::ch{chapter}"] = data

    def save_archive(self, name: str, chapter: int, data: dict, path: str | None = None) -> None:
        """Write-through: Atomic write to archive file + update memory cache."""
        p = path if path is not None else os.path.join(
            get_character_archive_dir(chapter), f"{name}_ch{chapter:02d}_archive.json"
        )
        self._atomic_write_json(p, data)
        self._archive_cache[f"{name}::ch{chapter}"] = data

    def get_archive(self, name: str, chapter: int) -> dict | None:
        key = f"{name}::ch{chapter}"
        if key in self._archive_cache:
            return self._archive_cache[key]
        path = os.path.join(
            get_character_archive_dir(chapter), f"{name}_ch{chapter:02d}_archive.json"
        )
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            data: dict[Any, Any] = cast(dict[Any, Any], json.load(f))
        self._archive_cache[key] = data
        return data

    def evict_archive_from(self, chapter: int) -> int:
        victims = [k for k in self._archive_cache if int(k.rsplit("::ch", 1)[1]) >= chapter]
        for k in victims:
            del self._archive_cache[k]
        return len(victims)

    def evict_archive_for(self, name: str) -> int:
        """Evict all chapter cache entries of a single character (regardless of chapter number)."""
        prefix = f"{name}::ch"
        victims = [k for k in self._archive_cache if k.startswith(prefix)]
        for k in victims:
            del self._archive_cache[k]
        return len(victims)

    def preload_archives(self, chapter: int) -> dict[str, dict]:
        result: dict[str, dict] = {}
        d = get_character_archive_dir(chapter)
        if not os.path.isdir(d):
            return result
        suffix = f"_ch{chapter:02d}_archive.json"
        for fname in os.listdir(d):
            if not fname.endswith(suffix):
                continue
            name = fname[: -len(suffix)]
            data = self.get_archive(name, chapter)
            if data:
                result[name] = data
        return result
