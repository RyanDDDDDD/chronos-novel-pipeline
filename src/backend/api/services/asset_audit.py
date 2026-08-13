"""Quick review of Agent assets at runtime."""
from __future__ import annotations

import json as _json
from pathlib import Path


def quick_audit_assets() -> list[dict]:
    """Quickly verify key Agent assets and return a list of failed entries (an empty list means all passed).

    Only files with .schema.json are verified; files without schema are skipped.
    Returns [{"asset": str, "error": str}, ...] on failure."""

    try:
        import jsonschema as _js
    except ImportError:
        return []

    from utils.paths import AGENTS_DIR

    agents_dir = Path(AGENTS_DIR)
    failures: list[dict] = []

    for agent_dir in agents_dir.iterdir():
        assets = agent_dir / "assets"
        if not assets.is_dir():
            continue
        for json_file in assets.glob("*.json"):
            if json_file.name.endswith(".schema.json"):
                continue
            schema_file = json_file.with_suffix("").with_suffix(".schema.json")
            if not schema_file.exists():
                continue
            try:
                with open(json_file, encoding="utf-8") as f:
                    data = _json.load(f)
                with open(schema_file, encoding="utf-8") as f:
                    schema = _json.load(f)
                _js.validate(data, schema)
            except Exception as e:
                failures.append({"asset": str(json_file), "error": str(e)})

    return failures
