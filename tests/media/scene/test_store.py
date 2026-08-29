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
    from media.scene import store
    from utils.paths import sandbox_scene_path

    fn = store.store_sandbox_scene_image(3, "b1", "r1", b"PNGDATA")
    assert fn.startswith("3_b1_r1-") and fn.endswith(".png")
    with open(sandbox_scene_path(fn), "rb") as f:
        assert f.read() == b"PNGDATA"
    assert store.list_sandbox_scene_images(3, "b1") == {"r1": fn}
    assert store.sandbox_scene_image_filename(3, "b1", "r1") == fn
    assert store.sandbox_scene_image_filename(3, "b1", "r-nope") is None


def test_regenerate_replaces_old_file():
    from media.scene import store
    from utils.paths import sandbox_scene_dir

    fn1 = store.store_sandbox_scene_image(3, "b1", "r1", b"A")
    time.sleep(1.1)
    fn2 = store.store_sandbox_scene_image(3, "b1", "r1", b"B")
    assert fn1 != fn2
    files = os.listdir(sandbox_scene_dir())
    assert fn2 in files and fn1 not in files
    assert store.list_sandbox_scene_images(3, "b1") == {"r1": fn2}


def test_scoped_by_chapter_and_branch():
    from media.scene import store

    store.store_sandbox_scene_image(3, "b1", "r1", b"A")
    store.store_sandbox_scene_image(4, "b1", "r1", b"B")
    store.store_sandbox_scene_image(3, "b2", "r1", b"C")
    assert set(store.list_sandbox_scene_images(3, "b1")) == {"r1"}
    assert (
        store.list_sandbox_scene_images(3, "b1")["r1"]
        != store.list_sandbox_scene_images(4, "b1")["r1"]
    )
