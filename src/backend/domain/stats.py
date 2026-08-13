"""LLM option preference statistics: pure key-value count storage.

Top-level structure (category / sub_category / name are all provided by the caller, the following are only example shapes):
  {
    "Category A": {"Subcategory 1": {"Option Name": 3}, "Subcategory 2": {...}},
    "Category B": {"Subcategory 1": {...}},
    "Proposal_Category A": {...},
  }

category / sub_category is provided by the caller (agent hook), and stats.py is not aware of specific themes."""
import json
from pathlib import Path

from utils.paths import VAR_DIR

_DEFAULT_PATH = Path(VAR_DIR) / "selection_stats.json"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    #Compatible with the old flat structure {name: count}, classified into the "Unknown" subcategory during migration
    migrated: dict = {}
    for cat, val in data.items():
        if not isinstance(val, dict) or not val:
            migrated[cat] = val
            continue
        first_v = next(iter(val.values()))
        if isinstance(first_v, int):
            remapped: dict = {}
            for name, count in val.items():
                remapped.setdefault("未知", {})[name] = count
            migrated[cat] = remapped
        else:
            migrated[cat] = val
    return migrated


def record(category: str, sub_category: str, names: list[str], path: Path | None = None) -> None:
    """
Record a batch of names into the category → sub_category bucket."""
    if not names:
        return
    p = path or _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    data = _load(p)
    bucket = data.setdefault(category, {}).setdefault(sub_category, {})
    for name in names:
        bucket[name] = bucket.get(name, 0) + 1
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
