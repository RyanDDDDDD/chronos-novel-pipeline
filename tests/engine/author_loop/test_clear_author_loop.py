"""clear_author_loop is the fresh-restart entry point (POST /api/author-loop/start {fresh:true}).
Everything chapter-scoped it leaves behind resurfaces on the re-run, so the per-stage scene
images have to go with the checkpoint + journal."""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _novel(monkeypatch, tmp_path):
    nid = "test-novel"
    (tmp_path / nid / "chapters").mkdir(parents=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", nid)
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_checkpoint.clear_chapter_thread",
        lambda _cp, _tid: None,
    )


def test_clear_author_loop_drops_the_chapters_scene_images():
    from engine.author_loop.build import clear_author_loop
    from media.scene import author_store
    from utils.paths import author_scene_dir

    fn6 = author_store.store_author_stage_scene_image(6, 0, b"A")
    author_store.store_author_stage_scene_image(6, 1, b"B")
    fn7 = author_store.store_author_stage_scene_image(7, 0, b"C")

    clear_author_loop(6)

    assert author_store.list_author_stage_scene_images(6) == {}
    assert author_store.list_author_stage_scene_images(7) == {"0": fn7}
    files = os.listdir(author_scene_dir())
    assert fn6 not in files and fn7 in files


def test_clear_author_loop_survives_a_chapter_with_no_scene_images():
    from engine.author_loop.build import clear_author_loop
    from media.scene import author_store

    clear_author_loop(9)

    assert author_store.list_author_stage_scene_images(9) == {}
