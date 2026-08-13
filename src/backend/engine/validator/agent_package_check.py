"""Agent Package structure verification (see docs/AGENT_PACKAGE.md).

For use by pytest and scripts/validate_agent_packages.py."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from engine.execution.agent_hook import AgentHook
from engine.execution.agent_plugin_loader import AgentPluginLoader

_SKIP_DIRS = frozenset({"_template", "__pycache__"})
_STRUCTURE_NODE_TYPES = frozenset({"start", "merge", "strip"})


def _is_unwired_package(pkg_dir: Path) -> bool:
    """
agent.meta.json Packages marked "unwired": true = library agents that are intentionally reserved and not yet connected to the manifest."""
    meta_path = pkg_dir / "agent.meta.json"
    if not meta_path.is_file():
        return False
    try:
        with open(meta_path, encoding="utf-8") as f:
            return bool(json.load(f).get("unwired") is True)
    except (json.JSONDecodeError, OSError):
        return False
_LEGACY_EXAMPLE = "EXAMPLE.md"
_SKIP_PROMPT_MD_SUFFIXES = (
    "_EXAMPLE.md",
    "_review.md",
    "_refine_analysis.md",
    "refine_analysis.md",
)

_REQUIRES_RE = re.compile(r"<!--\s*requires:\s*([^>]*?)-->", re.IGNORECASE)


def parse_prompt_requires(md_text: str) -> list[str]:
    """Extract the list of required fields declared by `<!-- requires: a, b, c -->` from prompt md (empty if none)."""
    m = _REQUIRES_RE.search(md_text)
    if not m:
        return []
    return [tok.strip() for tok in m.group(1).split(",") if tok.strip()]


def check_injects_contract(
    agent: str, injects: list[str], requires: list[str]
) -> list[str]:
    """
requires ⊆ injects otherwise an error will be reported. Injects is the hook declaration, and requires is the prompt declaration."""
    missing = [r for r in requires if r not in set(injects)]
    if not missing:
        return []
    return [
        f"hooks/packages/{agent}/: prompt 的 requires 声明了 {missing}，但 hook.injects 未提供"
        f"（injects={sorted(injects)}）；补 hook.injects 或修正 prompt requires / hook 注入。"
    ]


def _should_lint_prompt_md(path: Path) -> bool:
    if path.name in (_LEGACY_EXAMPLE, "README.md", "EXAMPLE.md"):
        return False
    return not any(
        path.name.endswith(suf) or path.name == suf for suf in _SKIP_PROMPT_MD_SUFFIXES
    )


def collect_injects_violations(agents_dir: str | Path) -> list[str]:
    """Scan the hooks/packages directory: the main prompt requires ⊆ hook.injects in the package with hook."""
    agents_dir = Path(agents_dir)
    loader = AgentPluginLoader(agents_dir)
    errs: list[str] = []
    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir() or entry.name in _SKIP_DIRS:
            continue
        hook = loader.load_hook(entry.name)
        if hook is None:
            continue
        injects = list(getattr(hook, "injects", None) or [])
        for md in sorted(entry.glob("*.md")):
            if not _should_lint_prompt_md(md):
                continue
            requires = parse_prompt_requires(md.read_text(encoding="utf-8"))
            errs.extend(check_injects_contract(entry.name, injects, requires))
    return errs


def check_agent_valid(
    agent: str,
    role: str,
    agents_dir: str | Path,
    *,
    hook: AgentHook | None = None,
) -> list[str]:
    """
Single (agent, role) validity check. Returns a list of missing reasons (empty = valid). catalog is shared with preflight."""
    agents_dir = Path(agents_dir)
    pkg = agents_dir / agent
    if not pkg.is_dir():
        return [f"hooks/packages/{agent}/: 目录不存在"]

    errs: list[str] = []
    if not (pkg / f"{role}.md").is_file():
        errs.append(f"hooks/packages/{agent}/: 缺少主 prompt {role}.md")

    return errs


def _manifest_nodes(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(manifest.get("nodes") or {})


def _is_agent_node(ndef: dict[str, Any]) -> bool:
    if ndef.get("type") in _STRUCTURE_NODE_TYPES:
        return False
    return bool(ndef.get("agent"))


def _roles_for_agent(
    nodes: dict[str, dict[str, Any]],
    loader: AgentPluginLoader,
    agent: str,
) -> tuple[list[str], list[str]]:
    """Return (roles, node_ids)."""
    roles: list[str] = []
    node_ids: list[str] = []
    for node_id, ndef in nodes.items():
        if not _is_agent_node(ndef) or ndef.get("agent") != agent:
            continue
        node_ids.append(node_id)
        cfg = {**ndef, "_node_id": node_id}
        role = loader.resolve_role(cfg) or agent
        if role not in roles:
            roles.append(role)
    return roles, node_ids


def _expected_meta(
    package: str,
    roles: list[str],
    node_ids: list[str],
) -> dict[str, Any]:
    return {
        "package": package,
        "roles": sorted(roles),
        "nodes": sorted(node_ids),
    }


def collect_expected_metas(
    manifest: dict[str, Any],
    agents_dir: str | Path,
) -> dict[str, dict[str, Any]]:
    """
Calculate the expected agent.meta.json content for each wired package by manifest + hook."""
    agents_dir = Path(agents_dir)
    nodes = _manifest_nodes(manifest)
    loader = AgentPluginLoader(agents_dir)
    by_agent: dict[str, list[str]] = {}
    for node_id, ndef in nodes.items():
        if not _is_agent_node(ndef):
            continue
        agent = ndef.get("agent")
        if not agent:
            continue
        by_agent.setdefault(agent, []).append(node_id)

    out: dict[str, dict[str, Any]] = {}
    for agent in sorted(by_agent):
        roles, node_ids = _roles_for_agent(nodes, loader, agent)
        out[agent] = _expected_meta(agent, roles, node_ids)
    return out


def agent_meta_json_line(meta: dict[str, Any]) -> str:
    return json.dumps(meta, ensure_ascii=False, indent=2) + "\n"


def sync_agent_meta_files(
    manifest: dict[str, Any],
    agents_dir: str | Path,
) -> list[str]:
    """Write agent.meta.json of all connected agents and return a list of written package names."""
    agents_dir = Path(agents_dir)
    written: list[str] = []
    for pkg, meta in collect_expected_metas(manifest, agents_dir).items():
        path = agents_dir / pkg / "agent.meta.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(agent_meta_json_line(meta), encoding="utf-8")
        written.append(pkg)
    return written


def check_agent_meta_drift(
    manifest: dict[str, Any],
    agents_dir: str | Path,
) -> list[str]:
    """
Return agent.meta.json description that is inconsistent with expectations (empty list = consistent)."""
    agents_dir = Path(agents_dir)
    drift: list[str] = []
    for pkg, meta in collect_expected_metas(manifest, agents_dir).items():
        path = agents_dir / pkg / "agent.meta.json"
        line = agent_meta_json_line(meta)
        if not path.is_file():
            drift.append(f"{path}: 缺失")
        elif path.read_text(encoding="utf-8") != line:
            drift.append(f"{path}: 与 manifest/hook 不同步")
    return drift


def _check_agent_meta_file(
    pkg_dir: Path,
    expected: dict[str, Any],
) -> list[str]:
    path = pkg_dir / "agent.meta.json"
    if not path.is_file():
        return [f"hooks/packages/{pkg_dir.name}/: 缺少 agent.meta.json（运行 sync_agent_meta.py）"]
    try:
        on_disk = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"hooks/packages/{pkg_dir.name}/agent.meta.json: JSON 无效 ({e})"]
    errs: list[str] = []
    if on_disk.get("package") != expected["package"]:
        errs.append(
            f"hooks/packages/{pkg_dir.name}/agent.meta.json: package 字段应为 {expected['package']!r}"
        )
    if sorted(on_disk.get("roles") or []) != expected["roles"]:
        errs.append(
            f"hooks/packages/{pkg_dir.name}/agent.meta.json: roles 与 manifest 不一致，"
            "请运行 sync_agent_meta.py"
        )
    return errs


def _check_no_legacy_example(pkg_dir: Path, roles: list[str]) -> list[str]:
    legacy = pkg_dir / _LEGACY_EXAMPLE
    if not legacy.is_file():
        return []
    #If any {role}_EXAMPLE.md already exists, the root EXAMPLE.md is a deprecated remnant
    for role in roles:
        if (pkg_dir / f"{role}_EXAMPLE.md").is_file():
            return [
                f"hooks/packages/{pkg_dir.name}/{_LEGACY_EXAMPLE}: 已废弃，"
                f"请删除并仅保留 {{role}}_EXAMPLE.md"
            ]
    return [
        f"hooks/packages/{pkg_dir.name}/{_LEGACY_EXAMPLE}: 请重命名为 "
        f"{roles[0]}_EXAMPLE.md（根目录 EXAMPLE.md 已废弃）"
    ]


def check_manifest_agent_packages(
    manifest: dict[str, Any],
    agents_dir: str | Path,
    *,
    require_meta: bool = True,
) -> list[str]:
    """Verify the package structure of the wired agent in the manifest. Returns a list of error messages (empty = passed)."""
    agents_dir = Path(agents_dir)
    nodes = _manifest_nodes(manifest)
    loader = AgentPluginLoader(agents_dir)
    errors: list[str] = []

    wired_agents: set[str] = set()
    agent_nodes: dict[str, list[str]] = {}

    for node_id, ndef in nodes.items():
        if not _is_agent_node(ndef):
            continue
        agent = ndef.get("agent")
        if not agent:
            continue
        wired_agents.add(agent)
        agent_nodes.setdefault(agent, []).append(node_id)

        cfg = {**ndef, "_node_id": node_id}
        role = loader.resolve_role(cfg) or agent
        pkg_dir = agents_dir / agent
        if not pkg_dir.is_dir():
            errors.append(f"节点 {node_id!r}: 缺少目录 hooks/packages/{agent}/")
            continue

        prompt_path = pkg_dir / f"{role}.md"
        if not prompt_path.is_file():
            errors.append(
                f"节点 {node_id!r}: 缺少主 prompt {prompt_path.name} "
                f"(agent={agent}, role={role})"
            )

    for agent, node_ids in agent_nodes.items():
        pkg_dir = agents_dir / agent
        if not pkg_dir.is_dir():
            continue
        roles, _ = _roles_for_agent(nodes, loader, agent)
        errors.extend(_check_no_legacy_example(pkg_dir, roles))
        if require_meta:
            expected = _expected_meta(agent, roles, node_ids)
            errors.extend(_check_agent_meta_file(pkg_dir, expected))

    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir() or entry.name in _SKIP_DIRS:
            continue
        if entry.name not in wired_agents:
            #Deliberately unconnected library agents (meta.unwired=true): reserved for backup and not counted as orphans.
            if _is_unwired_package(entry):
                continue
            errors.append(
                f"hooks/packages/{entry.name}/ 未出现在 manifest 中"
                "（deprecated 应删除或合并；若为有意保留的未接入库 agent，"
                "在其 agent.meta.json 标 \"unwired\": true）"
            )

    errors.extend(collect_injects_violations(agents_dir))
    return errors


def load_manifest(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))
