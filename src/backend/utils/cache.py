"""Generic in-process cache primitives shared across backend modules -- replaces the
"module-level dict + lazy-load + hand-rolled reset function" pattern duplicated in
config.py/content_packs.py/llm/factory.py/etc. Only what's actually needed today: a lazy
singleton and a keyed variant built from it, both sync (every current loader is a fast
in-memory/local-disk operation -- see docs/superpowers/specs/
2026-08-10-unified-cache-layer-sqlite-migration-design.md for why this doesn't need an
async sibling yet). Not thread-safe on its own -- callers needing cross-thread safety
(e.g. sqlite_store.py) wrap calls in their own lock, same as before this module existed."""
from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")
K = TypeVar("K")

_UNSET = object()


class LazyCache(Generic[T]):
    """A single lazily-computed value. `on_evict`, if given, runs on the old value when
    `invalidate()` actually clears a loaded value (never on an already-empty cache)."""

    def __init__(self, loader: Callable[[], T], *, on_evict: Callable[[T], None] | None = None) -> None:
        self._loader = loader
        self._on_evict = on_evict
        self._value: object = _UNSET

    def get(self, loader: Callable[[], T] | None = None) -> T:
        """`loader`, if given, overrides the constructor-time loader for this call only
        -- used when the recompute logic needs a value only known at the call site (e.g.
        config.py's `path` argument). Only matters on a cache miss; a hit returns the
        cached value regardless of what `loader` is passed, silently ignoring it (same
        semantics KeyedCache.get() already has for its per-call loader)."""
        if self._value is _UNSET:
            self._value = (loader or self._loader)()
        return self._value  # type: ignore[return-value]

    def peek(self) -> T | None:
        """Current value without triggering the loader; None if not yet loaded."""
        return None if self._value is _UNSET else self._value  # type: ignore[return-value]

    def invalidate(self) -> None:
        if self._value is not _UNSET:
            old = self._value
            self._value = _UNSET
            if self._on_evict:
                self._on_evict(old)  # type: ignore[arg-type]


class KeyedCache(Generic[K, T]):
    """dict of independently-lazy caches, one per key. Unlike LazyCache, the loader is
    supplied per get() call rather than fixed at construction -- real call sites (e.g.
    sqlite_store.py's per-novel db vs registry_store.py's registry db) need different
    construction logic for the same underlying cache, so a single construction-time
    loader doesn't fit. `on_evict` (if given) applies uniformly to every key."""

    def __init__(self, *, on_evict: Callable[[T], None] | None = None) -> None:
        self._on_evict = on_evict
        self._caches: dict[K, LazyCache[T]] = {}

    def get(self, key: K, loader: Callable[[], T]) -> T:
        if key not in self._caches:
            self._caches[key] = LazyCache(loader, on_evict=self._on_evict)
        return self._caches[key].get()

    def invalidate(self, key: K) -> None:
        cache = self._caches.pop(key, None)
        if cache is not None:
            cache.invalidate()

    def discard_if(self, key: K, value: T) -> bool:
        """Remove `key` only if its currently-cached value IS `value` (identity check,
        not equality). Never calls on_evict -- for callers that own cleanup of their own
        reference themselves and only need "stop the shared cache from handing this out
        again." Returns whether anything was removed."""
        cache = self._caches.get(key)
        if cache is not None and cache.peek() is value:
            del self._caches[key]
            return True
        return False

    def clear(self) -> None:
        """Invalidate every cached key (on_evict, if given, still runs per key) -- e.g.
        test teardown simulating a cold process restart."""
        for key in list(self._caches):
            self.invalidate(key)
