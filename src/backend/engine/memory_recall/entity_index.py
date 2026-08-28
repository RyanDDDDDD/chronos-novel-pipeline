"""Deterministic keyword vocabulary for story_sandbox and plot character-presence derivation:
two Aho-Corasick automata sharing the same lore given_name source. `scan_entities`'s vocab is
given_name ∪ world factions/geography/races proper nouns ∪ relationship-graph relational-term
aliases (from_ref_terms/to_ref_terms resolved to canonical given_name) ∪ given-name-fragment
aliases -- used by recall.py for event/lore recall, where a false-positive match is low-stakes
(recall content is supplementary, gated further by active_cast onstage checks). `scan_characters`'s
vocab is given_name ∪ given-name-fragment aliases ONLY -- no world nouns, no relational-term
aliases -- used by cast_tracker.py to track which characters earn a full persona card in the
actual prose prompt, and by plot_library's stage-roster consumers (plot_outline.py/
skeleton_seed.py/skeleton_pipeline.py/timeline_seed.py) to extract who's present in a plot stage
at read time, where a false positive is high-stakes (see
docs/superpowers/specs/2026-07-26-sandbox-present-vs-related-cast-design.md for why the
relational-term alias layer was dropped here specifically: a relational term like this novel's
genre-typical "废物" epithet can be non-ambiguous in the graph today yet get reused for a
different character tomorrow, or appear in prose the graph never modeled at all). Given-name-
fragment aliases (see _name_fragment_alias_map) don't carry that reassignment risk -- they're
derived from the canonical given_name itself, not free text -- so both automata include them.
No embeddings; plain Aho-Corasick substring match, never address_ref/self_ref. See
docs/superpowers/specs/2026-07-15-story-sandbox-recall-scan-scale-cooldown-design.md (original
automaton-caching design, for scan_entities),
docs/superpowers/specs/2026-07-18-sandbox-free-mode-dynamic-cast-design.md (scan_characters),
docs/superpowers/specs/2026-07-20-sandbox-relation-term-entity-alias-design.md (relational-term
alias layer, scan_entities only as of the present/related redesign), and
docs/superpowers/specs/2026-07-28-plot-stage-characters-derivation-design.md (given-name-fragment
alias layer, added after real-data migration surfaced that compound given names like 天童爱丽丝
are commonly referred to by given-name-only in prose)."""
from __future__ import annotations

import asyncio

import ahocorasick
from utils.cache import KeyedCache

_WORLD_NAMED_LISTS = ("factions", "geography", "races", "power_system", "core_themes")

_automaton_cache: KeyedCache[str, ahocorasick.Automaton] = KeyedCache()
_character_automaton_cache: KeyedCache[str, ahocorasick.Automaton] = KeyedCache()
_persisted_entries: dict[str, dict[str, tuple[set[str], dict[str, str]]]] = {}
# Set only during automaton rebuild so vocab + alias map share one lore snapshot.
_building_character_names: set[str] | None = None


def _read_character_names() -> set[str]:
    from repositories import get_lore_repo

    names: set[str] = set()
    try:
        for c in get_lore_repo().list_raw():
            if isinstance(c, dict):
                name = str(c.get("given_name") or "").strip()
                if name:
                    names.add(name)
    except (OSError, TypeError):
        pass
    return names


def _character_names() -> set[str]:
    """Lore given_name set only. Missing/corrupt source contributes nothing -- never raises."""
    if _building_character_names is not None:
        return _building_character_names
    return _read_character_names()


def _character_alias_map() -> dict[str, str]:
    """Third-person relational-term aliases (e.g. 妹妹/师傅) derived from the relationship
    graph's edges (from_ref_terms/to_ref_terms), resolved to the character's given_name --
    lets scan_entities/scan_characters recognize an existing character even when prose only
    ever calls them by a relational term, never their given_name. A term is dropped (never
    guessed) if it collides with a real given_name (must not shadow a direct-name match) or
    maps to more than one distinct given_name across the graph (ambiguous). Missing/corrupt
    graph source contributes nothing -- never raises."""
    from engine.setup.cast.relationship_graph import iter_edges, load_graph

    names = _character_names()
    candidates: dict[str, set[str]] = {}
    try:
        graph = load_graph()
        for e in iter_edges(graph):
            for term in e["from_ref_terms"]:
                candidates.setdefault(term, set()).add(e["from"])
            for term in e["to_ref_terms"]:
                candidates.setdefault(term, set()).add(e["to"])
    except (OSError, TypeError, KeyError):
        return {}

    return {
        term: next(iter(targets))
        for term, targets in candidates.items()
        if term not in names and len(targets) == 1
    }


def _name_fragment_alias_map(names: set[str]) -> dict[str, str]:
    """Given-name-derived aliases for prose that drops a compound name's surname portion
    (e.g. 上官铁柱 referred to as just 铁柱, or 司马相如 as 相如) -- unlike
    _character_alias_map's relational-term aliases (free text describing a relationship,
    which can get reassigned to a different character over time or never appear in the
    graph at all), these are derived directly from the canonical given_name itself, so the
    collision/reassignment risk _character_alias_map's docstring warns about doesn't apply
    -- safe to use even in scan_characters's high-stakes vocab. Tries dropping the first 1
    or 2 characters (covers both single- and double-character surname conventions,
    including the Japanese-style compound surnames common in this genre); a candidate
    fragment is dropped (never guessed) if it's under 2 characters (too ambiguous to be
    useful on its own), collides with any character's own given_name (must not shadow a
    direct-name match), or is produced by more than one character (ambiguous)."""
    candidates: dict[str, set[str]] = {}
    for name in names:
        for strip in (1, 2):
            frag = name[strip:]
            if len(frag) >= 2:
                candidates.setdefault(frag, set()).add(name)
    return {
        frag: next(iter(targets))
        for frag, targets in candidates.items()
        if frag not in names and len(targets) == 1
    }


def _world_keyword_alias_map(vocab: set[str]) -> dict[str, str]:
    """Clue-word alias layer for power_system/core_themes (and, generically, any
    _WORLD_NAMED_LISTS entry) whose optional `keywords` describe an abstract concept prose
    rarely names literally -- lets scan_entities resolve a keyword mention back to the entry's
    canonical name so it can cross-reference event `entities` the same way a direct name match
    does. Same "never guess" collision policy as _character_alias_map/_name_fragment_alias_map:
    a keyword is dropped (not registered) if it collides with any name already in `vocab` (must
    not shadow a direct name match) or is shared by more than one distinct entry name across the
    five lists (ambiguous). Missing/corrupt world source contributes nothing -- never raises.
    See docs/superpowers/specs/2026-08-11-power-system-core-themes-recall-automaton-v2-design.md.
    """
    from repositories import get_world_repo

    candidates: dict[str, set[str]] = {}
    try:
        bible = get_world_repo().get() or {}
        for key in _WORLD_NAMED_LISTS:
            for item in bible.get(key) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                for kw in item.get("keywords") or []:
                    kw = str(kw).strip()
                    if kw:
                        candidates.setdefault(kw, set()).add(name)
    except (OSError, TypeError):
        return {}

    return {
        kw: next(iter(targets))
        for kw, targets in candidates.items()
        if kw not in vocab and len(targets) == 1
    }


def build_entity_vocab() -> set[str]:
    """Union of cast given_name and world factions/geography/races name. Any missing/corrupt
    source contributes nothing -- never raises."""
    vocab = _character_names()

    try:
        from repositories import get_world_repo

        bible = get_world_repo().get() or {}
        for key in _WORLD_NAMED_LISTS:
            for item in bible.get(key) or []:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        vocab.add(name)
    except (OSError, TypeError):
        pass

    return vocab


def build_character_vocab() -> set[str]:
    """Lore given_name only -- no world nouns. See module docstring for why this is a separate
    vocab from build_entity_vocab rather than a filter over it."""
    return _character_names()


def invalidate_entity_vocab_cache(novel_id: str | None = None) -> None:
    """Drop this novel's cached automata (both in-memory and the persisted-entries bookkeeping
    used to re-persist on next rebuild) -- call whenever lore/world data may have changed under
    it. Next scan_entities/scan_characters call rebuilds lazily from fresh repo reads and
    re-persists. novel_id=None invalidates the currently active novel's shard."""
    from utils.paths import active_novel_id

    nid = novel_id or active_novel_id()
    _automaton_cache.invalidate(nid)
    _character_automaton_cache.invalidate(nid)
    _persisted_entries.pop(nid, None)


def _persist_doc_key(kind: str) -> str:
    return f"entity_index_{kind}"


def _load_persisted_snapshot(novel_id: str, kind: str) -> tuple[set[str], dict[str, str]] | None:
    from repositories.sqlite_store import SqliteStore

    data = SqliteStore(novel_id).get_doc(_persist_doc_key(kind), "")
    if not isinstance(data, dict):
        return None
    vocab = set(data.get("vocab") or [])
    aliases = dict(data.get("aliases") or {})
    return vocab, aliases


def persist_automaton_cache(novel_id: str) -> None:
    """Snapshot this novel's current vocab+aliases (NOT the compiled Automaton object -- see
    module docstring) to disk, so a later process restart can skip re-scanning lore/world/
    relationship_graph and jump straight to _build_automaton(). Call after a successful build
    (see _get_automaton/_get_character_automaton), and after invalidate_entity_vocab_cache
    triggers a rebuild -- silently no-ops if this novel's automata aren't currently cached
    (nothing to persist)."""
    entry = _persisted_entries.get(novel_id)
    if entry is None:
        return
    from repositories.sqlite_store import SqliteStore

    store = SqliteStore(novel_id)
    for kind, (vocab, aliases) in entry.items():
        store.save_doc(
            _persist_doc_key(kind),
            "",
            {"vocab": sorted(vocab), "aliases": aliases},
        )


async def restore_persisted_automata() -> None:
    """Startup warm-up (registered with SCHEDULER.schedule_once, see api/hub.py): for every
    novel with a persisted snapshot on disk, rebuild its automata from the snapshot (skips the
    lore/world/relationship_graph repo scan entirely) so the first request against that novel
    doesn't pay a cold-build cost. Runs off the event loop's thread via asyncio.to_thread since
    it's pure synchronous file IO + CPU-bound automaton compilation."""
    await asyncio.to_thread(_restore_persisted_automata_sync)


def _restore_persisted_automata_sync() -> None:
    from repositories.registry_store import visible_ids_sorted

    try:
        novel_ids = visible_ids_sorted()
    except Exception:
        return
    for novel_id in novel_ids:
        for kind, cache in (("entity", _automaton_cache), ("character", _character_automaton_cache)):
            snapshot = _load_persisted_snapshot(novel_id, kind)
            if snapshot is None:
                continue
            vocab, aliases = snapshot

            def _load(
                vocab: set[str] = vocab,
                aliases: dict[str, str] = aliases,
            ) -> ahocorasick.Automaton:
                return _build_automaton(vocab, aliases)

            cache.get(novel_id, _load)
            _persisted_entries.setdefault(novel_id, {})[kind] = (vocab, aliases)


def _build_automaton(vocab: set[str], aliases: dict[str, str] | None = None) -> ahocorasick.Automaton:
    automaton = ahocorasick.Automaton()
    for name in vocab:
        automaton.add_word(name, name)
    for alias, canonical in (aliases or {}).items():
        automaton.add_word(alias, canonical)
    automaton.make_automaton()
    return automaton


def _scan(automaton: ahocorasick.Automaton, text: str) -> list[str]:
    """Aho-Corasick multi-pattern scan: single pass over text, O(len(text) + match count),
    independent of vocab size. Returns sorted unique matches (deterministic output); empty text
    -> []. Empty vocab -> empty automaton -> []."""
    if not text:
        return []
    if len(automaton) == 0:
        # pyahocorasick leaves an automaton built from zero words in TRIE state (never
        # transitions to AHOCORASICK), and .iter() raises AttributeError on it.
        return []
    return sorted({name for _end_index, name in automaton.iter(text)})


def _get_automaton() -> ahocorasick.Automaton:
    from utils.paths import active_novel_id

    global _building_character_names
    nid = active_novel_id()

    def _load() -> ahocorasick.Automaton:
        global _building_character_names
        _building_character_names = _read_character_names()
        try:
            vocab = build_entity_vocab()
            aliases = _character_alias_map()
            aliases.update(_name_fragment_alias_map(_building_character_names))
            aliases.update(_world_keyword_alias_map(vocab))
            automaton = _build_automaton(vocab, aliases)
            _persisted_entries.setdefault(nid, {})["entity"] = (vocab, aliases)
            persist_automaton_cache(nid)
            return automaton
        finally:
            _building_character_names = None
    return _automaton_cache.get(nid, _load)


def _get_character_automaton() -> ahocorasick.Automaton:
    from utils.paths import active_novel_id

    global _building_character_names
    nid = active_novel_id()

    def _load() -> ahocorasick.Automaton:
        global _building_character_names
        _building_character_names = _read_character_names()
        try:
            aliases = _name_fragment_alias_map(_building_character_names)
            vocab = build_character_vocab()
            automaton = _build_automaton(vocab, aliases)
            _persisted_entries.setdefault(nid, {})["character"] = (vocab, aliases)
            persist_automaton_cache(nid)
            return automaton
        finally:
            _building_character_names = None
    return _character_automaton_cache.get(nid, _load)


def scan_entities(text: str) -> list[str]:
    """Scan against the cast+world vocab -- used by recall.py for event/lore recall."""
    return _scan(_get_automaton(), text)


def scan_characters(text: str) -> list[str]:
    """Scan against the character-only vocab -- given_name plus given-name-fragment aliases
    (e.g. 天童爱丽丝 matched via its bare given name 爱丽丝), but NO relational-term aliases --
    used by cast_tracker.py for active-cast tracking (dynamic persona-card injection/removal)
    and by plot_library's stage-roster consumers for read-time plot-stage presence extraction.
    Deliberately excludes the relational-term alias layer scan_entities uses: a relational term
    (e.g. this novel's genre-typical "废物"/"主人" epithets) can be registered as one character's
    alias in the relationship graph today yet get reused narratively for a different character
    tomorrow (or in freeform prose the graph never sees at all) -- trusting it here would let an
    unrelated character earn a full persona card in the actual prose prompt on a false-positive
    match (see docs/superpowers/specs/2026-07-26-sandbox-present-vs-related-cast-design.md).
    Given-name-fragment aliases don't carry that risk (derived from the canonical given_name
    itself, not free text), so they're included -- see _name_fragment_alias_map.
    Characters connected to whoever IS confidently present are instead surfaced separately as
    background-only "相关角色" via cast.py::resolve_related_cast, sourced from the relationship
    graph directly rather than by re-scanning text for its ref_terms."""
    return _scan(_get_character_automaton(), text)
