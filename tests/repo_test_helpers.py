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
    init_store()
    repo.get_archive_repo().save(name, chapter, data)
