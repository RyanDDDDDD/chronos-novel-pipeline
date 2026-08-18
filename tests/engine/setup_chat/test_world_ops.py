"""world_ops mutators now thread a version through read/mutate/persist."""
from engine.setup.world.world_ops import persist_world_doc, set_scalar_field
from repo_test_helpers import init_store


def test_set_scalar_field_returns_version_zero_for_new_doc():
    init_store()
    ok, err, doc, version = set_scalar_field("tone", "dark")
    assert ok
    assert version == 0  # no doc persisted yet
    del err, doc


def test_persist_world_doc_succeeds_with_matching_version():
    init_store()
    ok, err, doc, version = set_scalar_field("tone", "dark")
    saved, save_err = persist_world_doc(doc, changed_field="tone", expected_version=version)
    assert saved
    del ok, err, save_err


def test_persist_world_doc_rejects_stale_version():
    init_store()
    ok, err, doc, version = set_scalar_field("tone", "dark")
    persist_world_doc(doc, changed_field="tone", expected_version=version)  # first write wins
    saved, save_err = persist_world_doc(doc, changed_field="tone", expected_version=version)  # stale
    assert not saved
    assert "已被修改" in save_err
    del ok, err
