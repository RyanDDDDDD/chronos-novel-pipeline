import asyncio

from utils import paths


def test_use_novel_overrides_then_restores(monkeypatch):
    monkeypatch.setattr(paths, "_active_novel_id", lambda: "global")
    assert paths.active_novel_id() == "global"
    with paths.use_novel("A"):
        assert paths.active_novel_id() == "A"
    assert paths.active_novel_id() == "global"  #Roll back after exiting


def test_use_novel_restores_on_exception(monkeypatch):
    monkeypatch.setattr(paths, "_active_novel_id", lambda: "global")
    try:
        with paths.use_novel("A"):
            raise ValueError("boom")
    except ValueError:
        pass
    assert paths.active_novel_id() == "global"  #Also reset in case of exception


def test_concurrent_coros_isolated(monkeypatch):
    monkeypatch.setattr(paths, "_active_novel_id", lambda: "global")

    async def worker(nid):
        with paths.use_novel(nid):
            await asyncio.sleep(0.01)
            return paths.active_novel_id()

    async def main():
        return await asyncio.gather(worker("A"), worker("B"))

    assert asyncio.run(main()) == ["A", "B"]  #The two coroutines are pinned to each other and do not cross each other.
