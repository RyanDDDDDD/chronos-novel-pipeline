"""Structured data Repository: SqliteStore / SQLModel original dict ↔ business entity."""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.exc import StaleDataError
from sqlmodel import col, select
from utils.paths import active_novel_id

from repositories.document_store import get_document
from repositories.engine import archive_cache_for, session_for
from repositories.entities import ChapterOutline, Character, CharacterArchive
from repositories.models import (
    CharacterArchive as CharacterArchiveModel,
)
from repositories.models import (
    LoreCharacter,
    PlotChapter,
    RelationshipEdge,
    SandboxEvent,
    TimelineSnapshot,
)
from repositories.plot_outline import stages_to_segments
from repositories.sqlite_store import SqliteStore


class SqliteLoreRepository:
    def __init__(self, novel_id_or_store: str | SqliteStore | None = None) -> None:
        if isinstance(novel_id_or_store, str):
            self._nid: str | None = novel_id_or_store
        elif novel_id_or_store is not None and hasattr(novel_id_or_store, "_novel_id"):
            self._nid = novel_id_or_store._novel_id
        else:
            self._nid = None

    @staticmethod
    def _lore_row_key(cd: dict[str, Any], seq: int) -> str:
        name = cd.get("name")
        if isinstance(name, str) and name:
            return name
        return f"__idx_{seq}__"

    def _story_config(self) -> dict[str, dict[str, Any]]:
        doc = get_document(self._nid, "story_character_config")
        if isinstance(doc, dict):
            return doc
        return {}

    def _merge_story_extensions(self, char: dict[str, Any], name: str) -> None:
        ext = self._story_config().get(name)
        if isinstance(ext, dict):
            char.setdefault("extensions", {})
            char["extensions"].update(ext)

    def get_character(self, name: str) -> Character | None:
        with session_for(self._nid) as s:
            row = s.exec(select(LoreCharacter).where(col(LoreCharacter.name) == name)).one_or_none()
            if row is None:
                return None
            char = dict(row.data_json)
        char.setdefault("extensions", {})
        self._merge_story_extensions(char, name)
        return Character(**char)

    def list_characters(self) -> list[Character]:
        with session_for(self._nid) as s:
            rows = s.exec(select(LoreCharacter).order_by(col(LoreCharacter.seq))).all()
            raw_list = [dict(r.data_json) for r in rows]
        result: list[Character] = []
        cfg = self._story_config()
        for char in raw_list:
            name = char.get("name")
            if not name:
                continue
            c = dict(char)
            c.setdefault("extensions", {})
            ext = cfg.get(name)
            if isinstance(ext, dict):
                c["extensions"].update(ext)
            result.append(Character(**c))
        return result

    def list_raw(self) -> list[dict[str, Any]]:
        with session_for(self._nid) as s:
            rows = s.exec(select(LoreCharacter).order_by(col(LoreCharacter.seq))).all()
            return [dict(r.data_json) for r in rows]

    def get_story_config(self) -> dict[str, Any]:
        return self._story_config()

    def save_all(self, chars: list[dict[str, Any]], path: str | None = None) -> None:
        del path
        with session_for(self._nid) as s:
            incoming = [
                (self._lore_row_key(cd, seq), cd, seq) for seq, cd in enumerate(chars)
            ]
            existing_rows = s.exec(select(LoreCharacter)).all()
            existing = {r.name: r.id for r in existing_rows}
            incoming_names = {key for key, _, _ in incoming}
            seen_incoming: set[str] = set()

            for name, cid in list(existing.items()):
                if name in incoming_names:
                    continue
                s.exec(delete(CharacterArchiveModel).where(col(CharacterArchiveModel.character_id) == cid))  # type: ignore[arg-type]
                s.exec(delete(TimelineSnapshot).where(col(TimelineSnapshot.character_id) == cid))  # type: ignore[arg-type]
                s.exec(
                    delete(RelationshipEdge).where(  # type: ignore[arg-type]
                        or_(
                            col(RelationshipEdge.from_character_id) == cid,
                            col(RelationshipEdge.to_character_id) == cid,
                        )
                    )
                )
                s.exec(delete(LoreCharacter).where(col(LoreCharacter.id) == cid))  # type: ignore[arg-type]

            for key, cd, seq in incoming:
                if key in existing or key in seen_incoming:
                    row = s.exec(select(LoreCharacter).where(col(LoreCharacter.name) == key)).one()
                    row.data_json = cd
                    row.seq = seq
                else:
                    s.add(LoreCharacter(name=key, data_json=cd, seq=seq))
                seen_incoming.add(key)
            s.commit()

    def upsert_character(self, char: dict[str, Any]) -> None:
        char_name = char.get("name")
        roster = [c for c in self.list_raw() if c.get("name") != char_name]
        roster.append(char)
        self.save_all(roster)

    def get_character_with_version(self, name: str) -> tuple[dict[str, Any], int] | None:
        with session_for(self._nid) as s:
            row = s.exec(select(LoreCharacter).where(col(LoreCharacter.name) == name)).one_or_none()
            if row is None:
                return None
            char = dict(row.data_json)
            ver = row.version
        char.setdefault("extensions", {})
        self._merge_story_extensions(char, name)
        return char, ver

    def save_character_if_version_matches(
        self, name: str, data: dict[str, Any], expected_version: int,
    ) -> int | None:
        new_key = data.get("name")
        if not isinstance(new_key, str) or not new_key:
            new_key = name
        with session_for(self._nid) as s:
            obj = s.exec(select(LoreCharacter).where(col(LoreCharacter.name) == name)).one_or_none()
            if obj is None or obj.version != expected_version:
                return None
            obj.data_json = data
            obj.name = new_key
            flag_modified(obj, "data_json")
            try:
                s.commit()
            except (StaleDataError, IntegrityError):
                s.rollback()
                return None
            s.refresh(obj)
            return int(obj.version) if obj.version is not None else None

    def delete_character_if_version_matches(self, name: str, expected_version: int) -> bool:
        with session_for(self._nid) as s:
            obj = s.exec(select(LoreCharacter).where(col(LoreCharacter.name) == name)).one_or_none()
            if obj is None or obj.version != expected_version:
                return False
            cid = obj.id
            s.exec(delete(CharacterArchiveModel).where(col(CharacterArchiveModel.character_id) == cid))  # type: ignore[arg-type]
            s.exec(delete(TimelineSnapshot).where(col(TimelineSnapshot.character_id) == cid))  # type: ignore[arg-type]
            s.exec(
                delete(RelationshipEdge).where(  # type: ignore[arg-type]
                    or_(
                        col(RelationshipEdge.from_character_id) == cid,
                        col(RelationshipEdge.to_character_id) == cid,
                    )
                )
            )
            s.delete(obj)
            try:
                s.commit()
                return True
            except (StaleDataError, IntegrityError):
                s.rollback()
                return False


class SqlitePlotRepository:
    def __init__(self, novel_id_or_store: str | SqliteStore | None = None) -> None:
        if isinstance(novel_id_or_store, str):
            self._nid: str | None = novel_id_or_store
        elif novel_id_or_store is not None and hasattr(novel_id_or_store, "_novel_id"):
            self._nid = novel_id_or_store._novel_id
        else:
            self._nid = None

    def get_outline(self, chapter: int) -> ChapterOutline | None:
        with session_for(self._nid) as s:
            row = s.get(PlotChapter, chapter)
            if row is None:
                return None
            data = dict(row.data_json)
            data["chapter"] = chapter
            return ChapterOutline(**data)

    def chapter_segments(self, chapter: int) -> tuple[str | None, list[dict[str, Any]]]:
        with session_for(self._nid) as s:
            row = s.get(PlotChapter, chapter)
            if row is None:
                return None, []
            return stages_to_segments(row.data_json)

    def chapter_core_xp(self, chapter: int) -> list[str]:
        with session_for(self._nid) as s:
            row = s.get(PlotChapter, chapter)
            if row is None or not isinstance(row.data_json, dict):
                return []
            xp = row.data_json.get("core_xp")
            return [str(x) for x in xp] if isinstance(xp, list) else []

    def list_plot(self) -> list[dict[str, Any]]:
        with session_for(self._nid) as s:
            rows = s.exec(select(PlotChapter).order_by(col(PlotChapter.chapter))).all()
            return [dict(r.data_json) for r in rows]

    def list_raw(self) -> list[dict[str, Any]]:
        with session_for(self._nid) as s:
            rows = s.exec(select(PlotChapter).order_by(col(PlotChapter.seq))).all()
            return [dict(r.data_json) for r in rows]

    def save_all(self, chapters: list[dict[str, Any]] | dict[str, Any], path: str | None = None) -> None:
        del path
        items = list(chapters.values()) if isinstance(chapters, dict) else list(chapters)
        with session_for(self._nid) as s:
            incoming: list[tuple[int, dict[str, Any], int]] = []
            for seq, ch in enumerate(items):
                chapter_num = ch.get("chapter")
                if chapter_num is None:
                    continue
                incoming.append((int(chapter_num), ch, seq))
            incoming_chapters = {num for num, _, _ in incoming}
            existing_rows = s.exec(select(PlotChapter)).all()
            existing = {r.chapter for r in existing_rows}

            for chapter_num in existing - incoming_chapters:
                s.exec(delete(CharacterArchiveModel).where(col(CharacterArchiveModel.chapter) == chapter_num))  # type: ignore[arg-type]
                s.exec(delete(TimelineSnapshot).where(col(TimelineSnapshot.chapter) == chapter_num))  # type: ignore[arg-type]
                s.exec(delete(SandboxEvent).where(col(SandboxEvent.chapter) == chapter_num))  # type: ignore[arg-type]
                s.exec(delete(PlotChapter).where(col(PlotChapter.chapter) == chapter_num))  # type: ignore[arg-type]

            for chapter_num, ch, seq in incoming:
                if chapter_num in existing:
                    row = s.get(PlotChapter, chapter_num)
                    if row is not None:
                        row.data_json = ch
                        row.seq = seq
                else:
                    s.add(PlotChapter(chapter=chapter_num, data_json=ch, seq=seq))
            s.commit()

    def upsert_chapter(self, chapter_data: dict[str, Any]) -> None:
        ch = chapter_data.get("chapter")
        if ch is None:
            return
        existing = self.list_plot()
        kept = [p for p in existing if p.get("chapter") != ch]
        kept.append(chapter_data)
        kept.sort(key=lambda p: p.get("chapter", 0))
        self.save_all(kept)

    def get_outline_with_version(self, chapter: int) -> tuple[dict[str, Any], int] | None:
        with session_for(self._nid) as s:
            row = s.get(PlotChapter, chapter)
            if row is None:
                return None
            return dict(row.data_json), row.version

    def save_chapter_if_version_matches(
        self, chapter: int, data: dict[str, Any], expected_version: int,
    ) -> int | None:
        with session_for(self._nid) as s:
            obj = s.get(PlotChapter, chapter)
            if obj is None or obj.version != expected_version:
                return None
            obj.data_json = data
            flag_modified(obj, "data_json")
            try:
                s.commit()
            except (StaleDataError, IntegrityError):
                s.rollback()
                return None
            s.refresh(obj)
            return int(obj.version) if obj.version is not None else None

    def delete_chapter_if_version_matches(self, chapter: int, expected_version: int) -> bool:
        with session_for(self._nid) as s:
            obj = s.get(PlotChapter, chapter)
            if obj is None or obj.version != expected_version:
                return False
            s.exec(delete(CharacterArchiveModel).where(col(CharacterArchiveModel.chapter) == chapter))  # type: ignore[arg-type]
            s.exec(delete(TimelineSnapshot).where(col(TimelineSnapshot.chapter) == chapter))  # type: ignore[arg-type]
            s.exec(delete(SandboxEvent).where(col(SandboxEvent.chapter) == chapter))  # type: ignore[arg-type]
            s.delete(obj)
            try:
                s.commit()
                return True
            except (StaleDataError, IntegrityError):
                s.rollback()
                return False


class SqliteArchiveRepository:
    def __init__(self, novel_id_or_store: str | SqliteStore | None = None) -> None:
        if isinstance(novel_id_or_store, str):
            self._nid: str | None = novel_id_or_store
        elif novel_id_or_store is not None and hasattr(novel_id_or_store, "_novel_id"):
            self._nid = novel_id_or_store._novel_id
        else:
            self._nid = None

    def _cache(self) -> dict[str, dict[str, Any]]:
        nid = self._nid or active_novel_id()
        return archive_cache_for(nid)

    def get(self, name: str, chapter: int) -> CharacterArchive | None:
        key = f"{name}::ch{chapter}"
        cache = self._cache()
        if key in cache:
            raw = cache[key]
            base = {k: v for k, v in raw.items() if k not in ("name", "chapter")}
            return CharacterArchive(name=name, chapter=chapter, **base)
        with session_for(self._nid) as s:
            char = s.exec(select(LoreCharacter).where(col(LoreCharacter.name) == name)).one_or_none()
            if char is None or char.id is None:
                return None
            row = s.get(CharacterArchiveModel, (char.id, chapter))
            if row is None:
                return None
            raw = dict(row.data_json)
        cache[key] = raw
        base = {k: v for k, v in raw.items() if k not in ("name", "chapter")}
        return CharacterArchive(name=name, chapter=chapter, **base)

    def put(self, name: str, chapter: int, archive: dict[str, Any]) -> None:
        self._cache()[f"{name}::ch{chapter}"] = archive

    def save(self, name: str, chapter: int, archive: dict[str, Any], path: str | None = None) -> None:
        del path
        with session_for(self._nid) as s:
            char = s.exec(select(LoreCharacter).where(col(LoreCharacter.name) == name)).one_or_none()
            if char is None or char.id is None:
                raise ValueError(f"角色「{name}」不在花名册中，无法写入档案。")
            cid = char.id
            obj = s.get(CharacterArchiveModel, (cid, chapter))
            if obj is None:
                s.add(CharacterArchiveModel(character_id=cid, chapter=chapter, data_json=archive))
            else:
                obj.data_json = archive
            s.commit()
        self._cache()[f"{name}::ch{chapter}"] = archive

    def preload(self, chapter: int) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        cache = self._cache()
        with session_for(self._nid) as s:
            stmt = (
                select(LoreCharacter.name, CharacterArchiveModel.data_json)
                .join(LoreCharacter, col(LoreCharacter.id) == col(CharacterArchiveModel.character_id))
                .where(col(CharacterArchiveModel.chapter) == chapter)
            )
            rows = s.exec(stmt).all()
            for name, data_json in rows:
                data = dict(data_json)
                key = f"{name}::ch{chapter}"
                cache[key] = data
                result[name] = data
        return result

    def list_built(self) -> dict[int, list[str]]:
        out: dict[int, list[str]] = {}
        with session_for(self._nid) as s:
            stmt = (
                select(CharacterArchiveModel.chapter, LoreCharacter.name)
                .join(LoreCharacter, col(LoreCharacter.id) == col(CharacterArchiveModel.character_id))
                .order_by(col(CharacterArchiveModel.chapter), col(LoreCharacter.name))
            )
            rows = s.exec(stmt).all()
            for chapter, name in rows:
                out.setdefault(int(chapter), []).append(str(name))
        return out

    def evict_from(self, chapter: int) -> int:
        with session_for(self._nid) as s:
            res = s.exec(delete(CharacterArchiveModel).where(col(CharacterArchiveModel.chapter) >= chapter))  # type: ignore[arg-type]
            s.commit()
            deleted = int(res.rowcount) if hasattr(res, "rowcount") else 0
        cache = self._cache()
        victims = [k for k in cache if int(k.rsplit("::ch", 1)[1]) >= chapter]
        for k in victims:
            cache.pop(k, None)
        return deleted

    def evict_for(self, name: str) -> int:
        cache = self._cache()
        prefix = f"{name}::ch"
        victims = [k for k in cache if k.startswith(prefix)]
        for k in victims:
            cache.pop(k, None)
        with session_for(self._nid) as s:
            char = s.exec(select(LoreCharacter).where(col(LoreCharacter.name) == name)).one_or_none()
            if char is None or char.id is None:
                return 0
            res = s.exec(delete(CharacterArchiveModel).where(col(CharacterArchiveModel.character_id) == char.id))  # type: ignore[arg-type]
            s.commit()
            return int(res.rowcount) if hasattr(res, "rowcount") else 0
