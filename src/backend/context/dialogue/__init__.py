"""Dialog chain neutral assist: archive parsing/expanding (theme scaffolding has been moved to hooks/context/)."""
from context.dialogue.scaffold import (
    expand_archives_to_stages,
    parse_character_archives,
)

__all__ = ["expand_archives_to_stages", "parse_character_archives"]
