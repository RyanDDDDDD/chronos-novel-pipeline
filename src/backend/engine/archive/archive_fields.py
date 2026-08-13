"""character_archive Single Source of Truth (SSOT) for top-level fields.

Archive top level = lore role fields − _STAGE_BOUND_FIELDS − personality + extensions + stages.
Pure function, no I/O: used for preflight context verification to statically derive legal field sets (available after cold start)."""
from __future__ import annotations

#Fields that evolve with the stage, are only collapsed within stages[], and are not copied to the top level of the archive.
_STAGE_BOUND_FIELDS = {
    "clothing", "clothing_dna",
    "self_ref", "address_ref", "gender", "physique",
    "sliders", "race", "identity_background",
}


def expected_archive_fields(lore_index: dict[str, dict]) -> set[str]:
    """
Returns the set of legal top-level fields for character_archive.

    lore_index: LoreIndexer.index(name -> role lore dict)."""

    fields: set[str] = set()
    for char in lore_index.values():
        fields |= set(char.keys())
    fields -= _STAGE_BOUND_FIELDS
    fields.discard("personality")
    fields |= {"extensions", "stages"}
    return fields
