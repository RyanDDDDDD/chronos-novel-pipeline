from __future__ import annotations


def test_lazy_cache_calls_loader_only_once():
    from utils.cache import LazyCache

    calls = []

    def loader():
        calls.append(1)
        return "value"

    cache = LazyCache(loader)
    assert cache.get() == "value"
    assert cache.get() == "value"
    assert len(calls) == 1


def test_lazy_cache_peek_before_and_after_load():
    from utils.cache import LazyCache

    cache = LazyCache(lambda: "value")
    assert cache.peek() is None
    cache.get()
    assert cache.peek() == "value"


def test_lazy_cache_invalidate_triggers_on_evict_with_old_value():
    from utils.cache import LazyCache

    evicted = []
    cache = LazyCache(lambda: "value", on_evict=lambda v: evicted.append(v))

    cache.get()
    cache.invalidate()

    assert evicted == ["value"]
    assert cache.peek() is None


def test_lazy_cache_invalidate_on_never_loaded_cache_is_noop():
    from utils.cache import LazyCache

    evicted = []
    cache = LazyCache(lambda: "value", on_evict=lambda v: evicted.append(v))

    cache.invalidate()  # never called get()

    assert evicted == []


def test_lazy_cache_reload_after_invalidate_calls_loader_again():
    from utils.cache import LazyCache

    calls = []

    def loader():
        calls.append(1)
        return f"value-{len(calls)}"

    cache = LazyCache(loader)
    assert cache.get() == "value-1"
    cache.invalidate()
    assert cache.get() == "value-2"
    assert len(calls) == 2


def test_keyed_cache_independent_keys_load_independently():
    from utils.cache import KeyedCache

    calls = {"a": 0, "b": 0}
    cache: KeyedCache[str, str] = KeyedCache()

    result_a = cache.get("a", lambda: (calls.__setitem__("a", calls["a"] + 1), "value-a")[1])
    result_b = cache.get("b", lambda: (calls.__setitem__("b", calls["b"] + 1), "value-b")[1])

    assert result_a == "value-a"
    assert result_b == "value-b"
    assert calls == {"a": 1, "b": 1}


def test_keyed_cache_hit_does_not_call_second_loader():
    from utils.cache import KeyedCache

    cache: KeyedCache[str, str] = KeyedCache()
    cache.get("a", lambda: "first")

    second_loader_calls = []

    def second_loader():
        second_loader_calls.append(1)
        return "second"

    result = cache.get("a", second_loader)

    assert result == "first"  # cached value wins, second loader never runs
    assert second_loader_calls == []


def test_keyed_cache_invalidate_only_affects_that_key():
    from utils.cache import KeyedCache

    evicted = []
    cache: KeyedCache[str, str] = KeyedCache(on_evict=lambda v: evicted.append(v))
    cache.get("a", lambda: "value-a")
    cache.get("b", lambda: "value-b")

    cache.invalidate("a")

    assert evicted == ["value-a"]
    # "b" still cached: getting it again with a loader that would raise proves no reload happened
    result_b = cache.get("b", lambda: (_ for _ in ()).throw(AssertionError("should not reload b")))
    assert result_b == "value-b"


def test_keyed_cache_invalidate_unknown_key_is_noop():
    from utils.cache import KeyedCache

    cache: KeyedCache[str, str] = KeyedCache()
    cache.invalidate("never-existed")  # must not raise


def test_keyed_cache_discard_if_removes_on_identity_match():
    from utils.cache import KeyedCache

    evicted = []
    cache: KeyedCache[str, object] = KeyedCache(on_evict=lambda v: evicted.append(v))
    value = object()
    cache.get("a", lambda: value)

    removed = cache.discard_if("a", value)

    assert removed is True
    assert evicted == []  # discard_if never calls on_evict
    # confirm it's actually gone: a fresh get() re-runs the loader
    calls = []
    cache.get("a", lambda: (calls.append(1), "new-value")[1])
    assert calls == [1]


def test_keyed_cache_discard_if_no_op_on_identity_mismatch():
    from utils.cache import KeyedCache

    cache: KeyedCache[str, object] = KeyedCache()
    original = object()
    cache.get("a", lambda: original)

    removed = cache.discard_if("a", object())  # different object

    assert removed is False
    assert cache.get("a", lambda: (_ for _ in ()).throw(AssertionError("should still be cached"))) is original


def test_lazy_cache_get_override_loader_used_on_miss():
    from utils.cache import LazyCache

    cache: LazyCache[str] = LazyCache(lambda: "default")
    result = cache.get(lambda: "override")

    assert result == "override"


def test_lazy_cache_get_override_loader_ignored_on_hit():
    from utils.cache import LazyCache

    cache: LazyCache[str] = LazyCache(lambda: "default")
    cache.get()  # loads "default", caches it

    result = cache.get(lambda: "override")

    assert result == "default"  # cache hit -- override loader never even called


def test_lazy_cache_get_without_override_still_works():
    from utils.cache import LazyCache

    calls = []

    def loader():
        calls.append(1)
        return "value"

    cache = LazyCache(loader)
    assert cache.get() == "value"
    assert cache.get() == "value"
    assert len(calls) == 1


def test_keyed_cache_clear_invalidates_all_keys():
    from utils.cache import KeyedCache

    cache: KeyedCache[str, str] = KeyedCache()
    calls = {"a": 0, "b": 0}

    def loader_a():
        calls["a"] += 1
        return "va"

    def loader_b():
        calls["b"] += 1
        return "vb"

    cache.get("a", loader_a)
    cache.get("b", loader_b)
    assert calls == {"a": 1, "b": 1}

    cache.clear()

    cache.get("a", loader_a)
    cache.get("b", loader_b)
    assert calls == {"a": 2, "b": 2}  # both keys reloaded after clear()


def test_keyed_cache_clear_calls_on_evict_per_key():
    from utils.cache import KeyedCache

    evicted: list[str] = []
    cache: KeyedCache[str, str] = KeyedCache(on_evict=evicted.append)
    cache.get("a", lambda: "va")
    cache.get("b", lambda: "vb")

    cache.clear()

    assert sorted(evicted) == ["va", "vb"]
