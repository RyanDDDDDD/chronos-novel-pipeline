"""Seed/assert SQLite-backed repositories in tests (runtime no longer reads JSON paths)."""
from __future__ import annotations

import repositories as repo


def init_store() -> None:
    repo.init_repositories()


def seed_world(data: dict) -> None:
    init_store()
    repo.get_world_repo().save(data)


def get_world() -> dict | None:
    init_store()
    return repo.get_world_repo().get()


def seed_lore(chars: list[dict]) -> None:
    init_store()
    repo.get_lore_repo().save_all(chars)


def lore_raw() -> list[dict]:
    init_store()
    return repo.get_lore_repo().list_raw()


def seed_plot(chapters: list[dict]) -> None:
    init_store()
    repo.get_plot_repo().save_all(chapters)


def save_archive(name: str, chapter: int, data: dict) -> None:
    """Persist an archive row, ensuring lore + plot FK parents exist first.

    Many older tests wrote archives for names/chapters never seeded into lore_characters /
    plot_chapters. With character_id + chapter FKs that silent orphaning is no longer allowed,
    so the helper auto-registers missing parents rather than forcing every call site to
    remember two extra seed calls."""
    init_store()
    lore = repo.get_lore_repo().list_raw()
    if not any(isinstance(c, dict) and c.get("name") == name for c in lore):
        repo.get_lore_repo().save_all([*lore, {"name": name}])
    plot = repo.get_plot_repo().list_raw()
    if not any(isinstance(c, dict) and int(c.get("chapter", -1)) == int(chapter) for c in plot):
        repo.get_plot_repo().save_all([
            *plot,
            {"chapter": int(chapter), "title": f"T{chapter}", "stages": []},
        ])
    repo.get_archive_repo().save(name, chapter, data)
