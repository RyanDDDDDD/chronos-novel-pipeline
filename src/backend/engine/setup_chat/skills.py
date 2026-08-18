"""setup-chat 渐进披露 skill 注册表：system prompt 只放元数据索引，正文按需加载。

磁盘格式收编社区标准（Agent Skills）：目录=skill、入口 SKILL.md（兼容旧 skill.md 与平铺 <name>.md）、
真 YAML frontmatter——标准字段 name/description 顶层，私有字段（kind/activate_*）放 metadata:
命名空间（兼容旧平键，迁移容错）。name 以目录名/文件名为权威（frontmatter 只做校验），根治
「目录名≠name 半残」。扫描按目录列表顺序合并、同名后者跳过（内建在前 → 内建优先）；外部导入
目录只贡献 prompt（正文+references），其代码永不执行——collect_skill_tools 只对内建目录开放。"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable

import yaml
from loguru import logger

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
#引用文件形式 <skill>/references/<file>：file 段不含路径分隔符（正则即拒绝穿越），扩展名白名单另查。
_REF_RE = re.compile(r"^([A-Za-z0-9_-]+)/references/([A-Za-z0-9_.\-]+)$")
_REF_EXTS = (".md", ".txt")
_META_KEYS = ("kind",)


def setup_chat_skill_dirs() -> list[str]:
    """注册表扫描目录：内建在前 → 已启用内容包贡献的目录 → 外部导入目录在后
    （内建/内容包同名冲突内建优先；导入目录永远最后，其 skill 只贡献 prompt 不执行代码）。"""
    from context.content_packs import contributed_dirs
    from utils.paths import IMPORTED_SKILLS_DIR, SETUP_CHAT_SKILLS_DIR

    return [
        SETUP_CHAT_SKILLS_DIR,
        *contributed_dirs("setup_chat_skill_dirs"),
        IMPORTED_SKILLS_DIR,
    ]


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _norm_meta_value(v: object) -> str:
    """YAML 值归一化成字符串；list → CSV（activate_requires 允许 YAML 列表写法，消费端 _split_csv 不变）。"""
    if isinstance(v, list):
        return ",".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip() if v is not None else ""


def _parse_skill(text: str) -> tuple[dict[str, str], str]:
    """YAML frontmatter 解析：首行 `---` 到下一个 `---` 之间 safe_load。

    私有字段先查 metadata: 嵌套、再回落顶层平键（迁移兼容）。YAML 坏/非 dict/无闭合 →
    视为无元数据、整段当正文（容错哲学不变：不因格式小错丢内容，lint 负责报错）。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    body_start: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body_start = i + 1
            break
    if body_start is None:
        return {}, text.strip()
    try:
        data = yaml.safe_load("\n".join(lines[1:body_start - 1]))
    except yaml.YAMLError:
        return {}, text.strip()
    if not isinstance(data, dict):
        return {}, text.strip()
    raw_nested = data.get("metadata")
    nested: dict = raw_nested if isinstance(raw_nested, dict) else {}
    meta: dict[str, str] = {}
    for key in ("name", "description"):
        if key in data:
            meta[key] = _norm_meta_value(data[key])
    for key in _META_KEYS:
        if key in nested:
            meta[key] = _norm_meta_value(nested[key])
        elif key in data:
            meta[key] = _norm_meta_value(data[key])
    return meta, "\n".join(lines[body_start:]).strip()


def _entry_path(base_dir: str, entry: str) -> str | None:
    """目录型 skill 的入口文件：SKILL.md（标准）优先，旧 skill.md 兼容；都缺 → None。"""
    d = os.path.join(base_dir, entry)
    for fname in ("SKILL.md", "skill.md"):
        p = os.path.join(d, fname)
        if os.path.isfile(p):
            return p
    return None


def list_skill_index(skills_dirs: list[str]) -> list[dict[str, str]]:
    """按目录顺序合并扫描，返回元数据索引（**绝不含正文**）；目录不存在 → 跳过。

    name 以目录名/文件名为权威，frontmatter name 只校验（不一致 warning）；
    同名后者跳过（内建在前 → 内建优先）。source 标注来源目录（首个=builtin）。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for di, skills_dir in enumerate(skills_dirs):
        try:
            entries = sorted(os.listdir(skills_dir))
        except OSError:
            continue
        for entry in entries:
            path = os.path.join(skills_dir, entry)
            if entry.endswith(".md") and os.path.isfile(path):
                name, text = entry[: -len(".md")], _read(path)
            elif os.path.isdir(path):
                ep = _entry_path(skills_dir, entry)
                if ep is None:
                    continue
                name, text = entry, _read(ep)
            else:
                continue
            if not _NAME_RE.match(name):
                continue
            meta, _ = _parse_skill(text)
            fm_name = meta.get("name", "")
            if fm_name and fm_name != name:
                logger.warning("[skills] {} 的 frontmatter name「{}」≠ 目录/文件名「{}」，以后者为准",
                               path, fm_name, name)
            if name in seen:
                logger.warning("[skills] 同名 skill「{}」已存在（内建优先），跳过 {}", name, path)
                continue
            seen.add(name)
            out.append({
                "name": name,
                "description": meta.get("description", ""),
                "kind": meta.get("kind", ""),
                "source": "builtin" if di == 0 else "imported",
            })
    return out


def load_skill_body(name: str, skills_dirs: list[str]) -> str | None:
    """按 name 取正文；或 `<skill>/references/<file>` 取 skill 目录内引用文件（社区标准的
    渐进披露多文件结构——正文里引用相对路径，agent 用同一 load_skill 工具按需取）。"""
    safe = (name or "").strip()
    ref = _REF_RE.match(safe)
    if ref:
        return _load_reference(ref.group(1), ref.group(2), skills_dirs)
    if not _NAME_RE.match(safe):
        return None
    for skills_dir in skills_dirs:
        flat = os.path.join(skills_dir, f"{safe}.md")
        candidate = flat if os.path.isfile(flat) else _entry_path(skills_dir, safe)
        if candidate is not None:
            _, body = _parse_skill(_read(candidate))
            return body or None
    return None


def _load_reference(skill: str, fname: str, skills_dirs: list[str]) -> str | None:
    """引用文件读取：只认 references/ 下 .md/.txt，realpath 必须锁在该 skill 的 references 内
    （正则已拒绝路径分隔符，realpath 是纵深防御——防符号链接指出去）。原样返回，不解析 frontmatter。"""
    if not _NAME_RE.match(skill) or not fname.lower().endswith(_REF_EXTS):
        return None
    for skills_dir in skills_dirs:
        if _entry_path(skills_dir, skill) is None:
            continue  #该目录没有这个 skill → 找下一个目录
        root = os.path.realpath(os.path.join(skills_dir, skill, "references"))
        p = os.path.realpath(os.path.join(root, fname))
        if not p.startswith(root + os.sep):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None
    return None


_PLOT_EXTENSION_KIND = "plot-extension"
_PLOT_EXTENSIONS_TOKEN = "{{PLOT_EXTENSIONS}}"
_DIRECTION_GUIDANCE_TOKEN = "{{DIRECTION_GUIDANCE}}"
_LENS_GUIDANCE_TOKEN = "{{LENS_GUIDANCE}}"
#题材中性 baseline：skeleton-expansion 步骤 2/3a 的候选构思引导，内容包（如成人向）可经
#ContentPack.chapter_direction_guidance/stage_lens_guidance 整段覆写，见 content_packs.py。
_DEFAULT_DIRECTION_GUIDANCE = (
    "自己构思 **3-5 条真正不同的整体叙事走向**（差异在剧情怎么走、情绪节奏、角色分工），"
    "禁涉及具体体位/姿势；"
)
_DEFAULT_LENS_GUIDANCE = "构思 2-4 个互不重复、且呼应全局走向的**突出角度**"
_CORE_XP_GUIDANCE_TOKEN = "{{CORE_XP_GUIDANCE}}"
_STAGE_DESCRIPTION_GUIDANCE_TOKEN = "{{STAGE_DESCRIPTION_GUIDANCE}}"
#题材中性 baseline：plot-interview 章级 core_xp / 段级 stage description 的构思引导，内容包
#（如成人向）可经 ContentPack.plot_core_xp_guidance/plot_stage_guidance 整段覆写。
_DEFAULT_CORE_XP_GUIDANCE = "本章核心体验/卖点，几个关键词"
_DEFAULT_STAGE_DESCRIPTION_GUIDANCE = "交代发生了什么、情绪与走向"


def render_skill_index(skills_dirs: list[str]) -> str:
    """索引渲染进 system prompt；无 skill → 空串。

    plot-extension 类不进全局常驻索引——只在骨架架构阶段经 {{PLOT_EXTENSIONS}} 动态披露，
    避免污染顶层入口 skill 列表。"""
    items = [it for it in list_skill_index(skills_dirs) if it.get("kind") != _PLOT_EXTENSION_KIND]
    if not items:
        return ""
    lines = ["## 可用引导技能（按需用 load_skill 取完整内容，别凭空发挥）"]
    lines += [f"- {it['name']}：{it['description']}" for it in items]
    return "\n".join(lines)


def render_plot_extension_menu(skills_dirs: list[str]) -> str:
    """kind=plot-extension 的 skill 菜单（name+description，绝不含正文）；无 → ''。"""
    items = [it for it in list_skill_index(skills_dirs) if it.get("kind") == _PLOT_EXTENSION_KIND]
    if not items:
        return ""
    lines = ["## 可用剧情拓展（按需 load_skill 取其 playbook，挑契合本段的织入；只用真实条目，勿自创）"]
    lines += [f"- {it['name']}：{it['description']}" for it in items]
    return "\n".join(lines)


def expand_skill_placeholders(body: str, skills_dirs: list[str]) -> str:
    """替换 skill 正文动态占位符：{{PLOT_EXTENSIONS}} → 拓展菜单；{{DIRECTION_GUIDANCE}}/
    {{LENS_GUIDANCE}}/{{CORE_XP_GUIDANCE}}/{{STAGE_DESCRIPTION_GUIDANCE}} → 内容包覆写或
    题材中性 baseline 引导文案。

    让架构 skill 免手写、自动跟注册表长：加一个 plot-extension skill 就自动列出。"""
    from context.content_packs import (
        active_chapter_direction_guidance,
        active_plot_core_xp_guidance,
        active_plot_stage_guidance,
        active_stage_lens_guidance,
    )

    if _PLOT_EXTENSIONS_TOKEN in body:
        menu = render_plot_extension_menu(skills_dirs) or "（暂无可用剧情拓展）"
        body = body.replace(_PLOT_EXTENSIONS_TOKEN, menu)
    if _DIRECTION_GUIDANCE_TOKEN in body:
        guidance = active_chapter_direction_guidance() or _DEFAULT_DIRECTION_GUIDANCE
        body = body.replace(_DIRECTION_GUIDANCE_TOKEN, guidance)
    if _LENS_GUIDANCE_TOKEN in body:
        guidance = active_stage_lens_guidance() or _DEFAULT_LENS_GUIDANCE
        body = body.replace(_LENS_GUIDANCE_TOKEN, guidance)
    if _CORE_XP_GUIDANCE_TOKEN in body:
        guidance = active_plot_core_xp_guidance() or _DEFAULT_CORE_XP_GUIDANCE
        body = body.replace(_CORE_XP_GUIDANCE_TOKEN, guidance)
    if _STAGE_DESCRIPTION_GUIDANCE_TOKEN in body:
        guidance = active_plot_stage_guidance() or _DEFAULT_STAGE_DESCRIPTION_GUIDANCE
        body = body.replace(_STAGE_DESCRIPTION_GUIDANCE_TOKEN, guidance)
    return body


def _load_skill_module(skills_dir: str, name: str) -> object | None:
    """Import one skill package's interface.py by path, adding its dir + assets/ subdir to
    sys.path first so it can import sibling modules (mirrors agent_plugin_loader's hook.py
    handling). Returns None if there's no interface.py, or the import raises -- a single bad
    package must not break the caller's assembly."""
    import importlib.util

    iface = os.path.join(skills_dir, name, "interface.py")
    if not os.path.exists(iface):
        return None
    pkg_dir = os.path.join(skills_dir, name)
    assets_dir = os.path.join(pkg_dir, "assets")
    for d in (pkg_dir, assets_dir):
        if d not in sys.path:
            sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(f"_skill_iface_{name}", iface)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 -- a single bad package must not break assembly
        logger.warning("[skills] 加载 {} 的 interface.py 失败（{}）: {}",
                       name, type(exc).__name__, exc)
        return None
    return mod


def collect_skill_tools(
    skills_dir: str,
    module_filter: Callable[[object], bool] | None = None,
    existing_tool_names: set[str] | None = None,
) -> list:
    """遍历包型 skill 的 interface.py，动态 import 收集其 TOOLS（langchain 工具列表）。

    **只对内建目录调用**（安全线：外部导入 skill prompt-only，其代码永不执行——调用方守约，
    本函数不接收目录列表正是为了不给导入目录留口子）。import 失败/属性缺 → 跳过 + warning
    （单个坏包不炸 agent 组装）。平铺 .md 不贡献工具。"""
    tools: list = []
    taken: set[str] = set(existing_tool_names or ())
    try:
        entries = sorted(os.listdir(skills_dir))
    except OSError:
        return tools
    for name in entries:
        if not _NAME_RE.match(name):
            continue  #跳过 .md 文件等（含点/非法字符）
        mod = _load_skill_module(skills_dir, name)
        if mod is None:
            continue
        if module_filter is not None and not module_filter(mod):
            continue
        mod_tools = getattr(mod, "TOOLS", None)
        if isinstance(mod_tools, list):
            for t in mod_tools:
                tname = getattr(t, "name", "")
                if tname in taken:
                    #撞内置工具或先收集的 skill 工具 → ToolNode 行为未定义，宁可少一个也不歧义
                    logger.warning("[skills] {} 的工具「{}」与已有工具重名，跳过", name, tname)
                    continue
                taken.add(tname)
                tools.append(t)
    return tools


def collect_single_skill_tools(skills_dir: str, name: str) -> list:
    """Load just one named skill package's own TOOLS -- used by story_sandbox's slash-
    triggered skill-suggestion path, which only ever needs one skill's tools per call (unlike
    collect_skill_tools's whole-directory sweep for setup_chat's persistent agent assembly).
    Same code-execution safety line as collect_skill_tools: caller must only pass a builtin
    skills dir. No interface.py / bad name / broken module -> []."""
    if not _NAME_RE.match(name):
        return []
    mod = _load_skill_module(skills_dir, name)
    if mod is None:
        return []
    mod_tools = getattr(mod, "TOOLS", None)
    return list(mod_tools) if isinstance(mod_tools, list) else []
