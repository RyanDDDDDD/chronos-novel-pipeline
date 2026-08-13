"""Shared fixtures for tests/api/.

tests/engine/ gets default novel-path isolation from tests/engine/conftest.py
(_isolate_novels_dir); tests/api/ had no equivalent, so any test here that
exercises a write path without individually isolating CHRONOS_NOVELS_DIR falls
through to the real registry and the real data/novels/<active>/ directory
instead of erroring.

Confirmed via a live incident: tests/api/test_setup_chat_attachments_api.py and
test_setup_chat_api.py upload/store attachments (fixed filenames like novel.txt,
novel.md, a.txt, page.png/page.jpg with solid-blue placeholder pixels) without
isolation, so every local test run persisted them into whichever novel happened
to be active at the time -- polluting several real novels' attachment libraries
with test fixture junk. See tests/engine/conftest.py for the reference pattern.

Unlike tests/engine/conftest.py, this deliberately does NOT also pin
CHRONOS_ACTIVE_NOVEL: several tests/api/ tests (e.g. test_novels_api.py) assert
on active-novel switching via the registry's is_active row, which a pinned env
var would permanently override. utils.paths._active_novel_id() already falls
back to the default novel id when the isolated registry has no active row, so
isolating just the novels dir is sufficient to stop real-data writes.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_novels_dir(monkeypatch, tmp_path):
    """Pin CHRONOS_NOVELS_DIR to a fresh per-test tmp directory by default."""
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
