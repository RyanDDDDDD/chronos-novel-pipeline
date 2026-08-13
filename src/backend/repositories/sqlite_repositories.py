"""Structured data Repository: SqliteStore original dict ↔ business entity."""
from __future__ import annotations

from repositories.entities import ChapterOutline, Character, CharacterArchive
from repositories.plot_outline import stages_to_segments
from repositories.sqlite_store import SqliteStore


class SqliteLoreRepository:
    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def get_character(self, name: str) -> Character | None:
        raw = self._store.get_lore(name)
        return Character(**raw) if raw is not None else None

    def list_characters(self) -> list[Character]:
        return [Character(**r) for r in self._store.list_lore()]

    def list_raw(self) -> list[dict]:
        return self._store.list_lore_raw()

    def get_story_config(self) -> dict:
        from utils.paths import story_character_config_path

        data = self._store.get_doc("story_character_config", story_character_config_path())
        return data if isinstance(data, dict) else {}

    def save_all(self, chars: list[dict], path: str | None = None) -> None:
        self._store.save_lore(chars, path=path)

    def upsert_character(self, char: dict) -> None:
        roster = [c for c in self._store.list_lore() if c.get("name") != char.get("name")]
        roster.append(char)
        self._store.save_lore(roster)


class SqlitePlotRepository:
    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def get_outline(self, chapter: int) -> ChapterOutline | None:
        raw = self._store.get_outline(chapter)
        if raw is None:
            return None
        return ChapterOutline(chapter=chapter, **raw)

    def chapter_segments(self, chapter: int) -> tuple[str | None, list[dict]]:
        raw = self._store.get_outline(chapter)
        if raw is None:
            return None, []
        return stages_to_segments(raw)

    def chapter_core_xp(self, chapter: int) -> list[str]:
        raw = self._store.get_outline(chapter)
        if not isinstance(raw, dict):
            return []
        xp = raw.get("core_xp")
        return [str(x) for x in xp] if isinstance(xp, list) else []

    def list_raw(self) -> list[dict]:
        return self._store.list_plot_raw()

    def save_all(self, chapters: list[dict] | dict, path: str | None = None) -> None:
        self._store.save_plot(chapters, path=path)

    def upsert_chapter(self, chapter_data: dict) -> None:
        ch = chapter_data.get("chapter")
        existing = self._store.list_plot()
        kept = [p for p in existing if p.get("chapter") != ch]
        kept.append(chapter_data)
        kept.sort(key=lambda p: p.get("chapter", 0))
        self._store.save_plot(kept)


class SqliteArchiveRepository:
    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def get(self, name: str, chapter: int) -> CharacterArchive | None:
        raw = self._store.get_archive(name, chapter)
        if raw is None:
            return None
        base = {k: v for k, v in raw.items() if k not in ("name", "chapter")}
        return CharacterArchive(name=name, chapter=chapter, **base)

    def put(self, name: str, chapter: int, archive: dict) -> None:
        self._store.put_archive(name, chapter, archive)

    def save(self, name: str, chapter: int, archive: dict, path: str | None = None) -> None:
        self._store.save_archive(name, chapter, archive, path=path)

    def preload(self, chapter: int) -> dict[str, dict]:
        return self._store.preload_archives(chapter)

    def list_built(self) -> dict[int, list[str]]:
        return self._store.list_archived_chapters()

    def evict_from(self, chapter: int) -> int:
        return self._store.evict_archive_from(chapter)

    def evict_for(self, name: str) -> int:
        return self._store.evict_archive_for(name)
