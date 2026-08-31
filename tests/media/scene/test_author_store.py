from __future__ import annotations

import os
import time

import pytest


@pytest.fixture(autouse=True)
def _novel(monkeypatch, tmp_path):
    nid = "test-novel"
    (tmp_path / nid / "chapters").mkdir(parents=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", nid)


def test_store_and_list_roundtrip():
    from media.scene import author_store
    from utils.paths import author_scene_path

    fn = author_store.store_author_stage_scene_image(6, 2, b"PNGDATA")
    assert fn.startswith("6_2-") and fn.endswith(".png")
    with open(author_scene_path(fn), "rb") as f:
        assert f.read() == b"PNGDATA"
    assert author_store.list_author_stage_scene_images(6) == {"2": fn}
    assert author_store.author_stage_scene_image_filename(6, 2) == fn
    assert author_store.author_stage_scene_image_filename(6, 99) is None


def test_regenerate_replaces_old_file():
    from media.scene import author_store
    from utils.paths import author_scene_dir

    fn1 = author_store.store_author_stage_scene_image(6, 2, b"A")
    time.sleep(1.1)
    fn2 = author_store.store_author_stage_scene_image(6, 2, b"B")
    assert fn1 != fn2
    files = os.listdir(author_scene_dir())
    assert fn2 in files and fn1 not in files
    assert author_store.list_author_stage_scene_images(6) == {"2": fn2}


def test_scoped_by_chapter():
    from media.scene import author_store

    author_store.store_author_stage_scene_image(6, 0, b"A")
    author_store.store_author_stage_scene_image(7, 0, b"B")
    assert set(author_store.list_author_stage_scene_images(6)) == {"0"}


def test_clear_removes_chapter_entries_and_files():
    from media.scene import author_store
    from utils.paths import author_scene_dir

    fn6 = author_store.store_author_stage_scene_image(6, 0, b"A")
    author_store.store_author_stage_scene_image(6, 1, b"B")
    fn7 = author_store.store_author_stage_scene_image(7, 0, b"C")

    author_store.clear_author_stage_scene_images(6)

    assert author_store.list_author_stage_scene_images(6) == {}
    assert author_store.list_author_stage_scene_images(7) == {"0": fn7}
    files = os.listdir(author_scene_dir())
    assert fn6 not in files and fn7 in files
