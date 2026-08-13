"""skill 注册表校验器：导入外部 skill 后一跑便知好没好（缺口 6 的最小 UX）。

只做静态检查 + 内建目录的 interface.py 试导入；**绝不执行导入目录（外部）代码**——
外部 skill 的安全立场是 prompt-only，lint 对 scripts/ 与导入目录 interface.py 只报告剥离。
level 语义：error = 运行期会坏/歧义（YAML 坏、同名冲突、内建 interface 失败、工具撞名）；
warning = 功能打折但能跑（缺 description、name 不一致、脚本剥离）。"""
from __future__ import annotations

import os

import yaml

from engine.setup_chat.skills import _NAME_RE, _entry_path, _parse_skill

Finding = tuple[str, str, str]  #(level, skill标识, 消息)


def _frontmatter_yaml_error(text: str) -> str | None:
    """区分「YAML 真坏」与「无 frontmatter」：_parse_skill 把两者都容错折叠，lint 要分开报。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None  #没写 frontmatter 不算错（缺 description 另报）
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                data = yaml.safe_load("\n".join(lines[1:i]))
            except yaml.YAMLError as exc:
                return str(exc).splitlines()[0]
            return None if isinstance(data, dict) else "frontmatter 不是键值映射"
    return "frontmatter 缺少闭合 ---"


def _iter_skills(skills_dir: str):
    """产出 (name, 入口文件路径, skill目录路径或None)；无入口的目录也产出（path=None）供报告。"""
    try:
        entries = sorted(os.listdir(skills_dir))
    except OSError:
        return
    for entry in entries:
        p = os.path.join(skills_dir, entry)
        if entry.endswith(".md") and os.path.isfile(p):
            yield entry[: -len(".md")], p, None
        elif os.path.isdir(p):
            yield entry, _entry_path(skills_dir, entry), p


def _check_builtin_interface(name: str, iface: str) -> list[Finding]:
    """内建 interface.py 试导入：失败=运行期工具静默消失，必须可诊断（D12）。"""
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location(f"_lint_iface_{name}", iface)
        if spec is None or spec.loader is None:
            return [("error", name, "interface.py 无法构建导入 spec")]
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:  #noqa: BLE001 — lint 面向任意坏包，逐个报告而非中断
        return [("error", name, f"interface.py 导入失败（{type(exc).__name__}）：{exc}")]
    if not isinstance(getattr(mod, "TOOLS", None), list):
        return [("error", name, "interface.py 缺少 TOOLS 列表导出")]
    return []


def lint_dirs(dirs: list[str]) -> list[Finding]:
    """按注册表同款合并规则扫描并报告问题；首个目录视为内建（允许执行其 interface.py）。"""
    findings: list[Finding] = []
    seen: dict[str, str] = {}  #name → 首次出现路径
    tool_names: set[str] = set()
    for di, skills_dir in enumerate(dirs):
        is_builtin = di == 0
        source = "内建" if is_builtin else "导入"
        for name, entry_file, pkg_dir in _iter_skills(skills_dir):
            ident = name
            if entry_file is None:
                findings.append(("warning", ident, f"[{source}] 目录无 SKILL.md/skill.md，不会进注册表"))
                continue
            if not _NAME_RE.match(name):
                findings.append(("error", ident, f"[{source}] 名字含非法字符（只允许字母数字-_）"))
                continue
            if name in seen:
                findings.append(("error", ident,
                                 f"[{source}] 与 {seen[name]} 同名冲突（前者优先，本目录版本被屏蔽）"))
                continue
            seen[name] = entry_file
            try:
                with open(entry_file, encoding="utf-8") as f:
                    text = f.read()
            except OSError as exc:
                findings.append(("error", ident, f"[{source}] 入口文件读取失败：{exc}"))
                continue
            yaml_err = _frontmatter_yaml_error(text)
            if yaml_err:
                findings.append(("error", ident, f"[{source}] frontmatter YAML 解析失败：{yaml_err}"))
            meta, _body = _parse_skill(text)
            if not meta.get("description"):
                findings.append(("warning", ident, f"[{source}] 缺 description（索引里没描述，agent 选不中）"))
            fm_name = meta.get("name", "")
            if fm_name and fm_name != name:
                findings.append(("warning", ident,
                                 f"[{source}] frontmatter name「{fm_name}」≠ 目录/文件名，以后者为准"))
            if pkg_dir is None:
                continue
            if os.path.isdir(os.path.join(pkg_dir, "scripts")):
                findings.append(("warning", ident,
                                 f"[{source}] 含 scripts/：本系统不执行脚本，该 skill 的脚本能力已剥离，"
                                 "仅正文与 references/ 生效"))
            iface = os.path.join(pkg_dir, "interface.py")
            if os.path.isfile(iface):
                if is_builtin:
                    iface_findings = _check_builtin_interface(name, iface)
                    findings.extend(iface_findings)
                    if not iface_findings:
                        findings.extend(_check_tool_conflicts(name, iface, tool_names))
                else:
                    findings.append(("warning", ident,
                                     "[导入] 含 interface.py：外部 skill 不执行代码，TOOLS 不会被收集"))
    return findings


def _check_tool_conflicts(name: str, iface: str, tool_names: set[str]) -> list[Finding]:
    """内建工具名跨包冲突（D11）：与运行期 collect_skill_tools 的跳过规则同判据。"""
    import importlib.util

    out: list[Finding] = []
    spec = importlib.util.spec_from_file_location(f"_lint_tools_{name}", iface)
    assert spec is not None and spec.loader is not None  #_check_builtin_interface 已验证可导入
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for t in getattr(mod, "TOOLS", []):
        tname = getattr(t, "name", "")
        if tname in tool_names:
            out.append(("error", name, f"工具「{tname}」与其它 skill 的工具重名（运行期会被跳过）"))
        else:
            tool_names.add(tname)
    return out
