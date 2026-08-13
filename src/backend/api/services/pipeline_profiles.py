"""Pipeline files: scan to enumerate, switch, clone/create, rename, delete, and migrate in one go.

File saved in config/pipelines/<id>/manifest.json (+ runtime author_loop_skill_prefs.json);
display name stores the top-level name field of the manifest (no need to create a new central registry, rely on disk scanning to enumerate)."""
from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any

from utils.paths import (
    CONFIG_DIR,
    active_pipeline_id,
    active_pointer_path,
    pipelines_dir,
)

#Manifest (migration source) of the old single pipeline; module-level constants facilitate monkeypatch testing.
LEGACY_MANIFEST = os.path.join(CONFIG_DIR, "pipeline_manifest.json")

_BLANK_MANIFEST_NODES = {"start": {"type": "start"}}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _profile_dir(pid: str) -> str:
    return os.path.join(pipelines_dir(), pid)


def _manifest_file(pid: str) -> str:
    return os.path.join(_profile_dir(pid), "manifest.json")


def _atomic_write(path: str, data: dict | str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(tmp, path)


def _existing_ids() -> list[str]:
    root = pipelines_dir()
    if not os.path.isdir(root):
        return []
    return [
        name for name in os.listdir(root)
        if os.path.isfile(_manifest_file(name))
    ]


def slugify(name: str) -> str:
    """
File system security slug: ASCII lowercase hyphen; pure non-ASCII (such as Chinese) pipeline-<n>."""
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    if slug:
        #If there is a conflict, the sequence number will be appended.
        base, n = slug, 1
        existing = set(_existing_ids())
        while slug in existing:
            n += 1
            slug = f"{base}-{n}"
        return slug
    #Pure Chinese/Symbols → Counting
    n = len(_existing_ids()) + 1
    existing = set(_existing_ids())
    while f"pipeline-{n}" in existing:
        n += 1
    return f"pipeline-{n}"


def list_profiles() -> list[dict]:
    """Scanning returns [{id, name, active}], sorted by name."""
    active = active_pipeline_id()
    out: list[dict] = []
    for pid in _existing_ids():
        try:
            man = json.loads(open(_manifest_file(pid), encoding="utf-8").read())
            name = man.get("name") if isinstance(man.get("name"), str) else pid
        except (OSError, json.JSONDecodeError):
            name = pid
        out.append({"id": pid, "name": name or pid, "active": pid == active})
    return sorted(out, key=lambda p: p["name"])


def set_active(pid: str) -> None:
    """
Switch the current pipeline; if pid does not exist, an error will be reported."""
    if not os.path.isfile(_manifest_file(pid)):
        raise ValueError(f"pipeline 不存在: {pid}")
    _atomic_write(active_pointer_path(), {"active": pid})


def create_profile(name: str, clone: bool = True) -> str:
    """Create a new file: clone=True copies the current active directory, otherwise a blank file containing only start is created. Return the new id."""
    pid = slugify(name)
    dst = _profile_dir(pid)
    if clone:
        src = _profile_dir(active_pipeline_id())
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            os.makedirs(dst, exist_ok=True)
    else:
        os.makedirs(dst, exist_ok=True)
    #Write a new name (the cloned manifest also overwrites the name)
    man_path = _manifest_file(pid)
    man: dict[str, Any] = {"nodes": dict(_BLANK_MANIFEST_NODES)}
    if os.path.isfile(man_path):
        try:
            man = json.loads(open(man_path, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            pass
    man["name"] = name
    _atomic_write(man_path, man)
    return pid


def rename_profile(pid: str, name: str) -> None:
    """
Only the name field of the manifest is changed, and the directory id remains unchanged (the name is changed but the location is not moved)."""
    man_path = _manifest_file(pid)
    if not os.path.isfile(man_path):
        raise ValueError(f"pipeline 不存在: {pid}")
    man = json.loads(open(man_path, encoding="utf-8").read())
    man["name"] = name
    _atomic_write(man_path, man)


def delete_profile(pid: str) -> None:
    """Delete directories; prohibit deletion of active and prohibit deletion until there is only one directory left."""
    ids = _existing_ids()
    if pid not in ids:
        raise ValueError(f"pipeline 不存在: {pid}")
    if pid == active_pipeline_id():
        raise ValueError("不能删除当前选中的 pipeline")
    if len(ids) <= 1:
        raise ValueError("至少保留一个 pipeline")
    shutil.rmtree(_profile_dir(pid))


def ensure_initialized() -> None:
    """
One-time idempotent migration:

    - Any file already exists → Do not move.
    - Otherwise if the old config/pipeline_manifest.json is in → move into default/ (the old file is retained).
    - Otherwise create a blank default.
    Finally, ensure that active.json points to an existing file."""

    if _existing_ids():
        _heal_active()
        return
    default_dir = _profile_dir("default")
    os.makedirs(default_dir, exist_ok=True)
    if os.path.isfile(LEGACY_MANIFEST):
        man = json.loads(open(LEGACY_MANIFEST, encoding="utf-8").read())
        man["name"] = "默认"
        _atomic_write(os.path.join(default_dir, "manifest.json"), man)
    else:
        _atomic_write(os.path.join(default_dir, "manifest.json"), {"name": "默认", "nodes": dict(_BLANK_MANIFEST_NODES)})
    _atomic_write(active_pointer_path(), {"active": "default"})


def _heal_active() -> None:
    """
When active points to a file that does not exist, correct it to the first existing file."""
    ids = _existing_ids()
    if active_pipeline_id() not in ids:
        _atomic_write(active_pointer_path(), {"active": sorted(ids)[0]})
