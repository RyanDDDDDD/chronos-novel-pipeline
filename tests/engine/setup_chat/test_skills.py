from engine.setup_chat import skills


def _write(d, name, text):
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


SKILL_A = """---
name: world-interview
description: 用户要建世界观时加载的访谈引导。
---

这是正文：固定 8 维顺序，不深挖支线。
"""


def test_parse_skill_separates_frontmatter_and_body():
    meta, body = skills._parse_skill(SKILL_A)
    assert meta == {"name": "world-interview", "description": "用户要建世界观时加载的访谈引导。"}
    assert body.startswith("这是正文")
    assert "不深挖支线" in body
    assert "name:" not in body  #frontmatter does not leak into the body


def test_parse_skill_no_frontmatter_returns_full_body():
    meta, body = skills._parse_skill("没有 frontmatter 的纯正文")
    assert meta == {}
    assert body == "没有 frontmatter 的纯正文"


def test_list_skill_index_returns_metadata_only(tmp_path):
    _write(tmp_path, "world-interview.md", SKILL_A)
    idx = skills.list_skill_index([str(tmp_path)])
    assert idx == [{
        "name": "world-interview",
        "description": "用户要建世界观时加载的访谈引导。",
        "kind": "",
        "source": "builtin",
    }]
    #Index never contains text
    assert all("不深挖支线" not in v for item in idx for v in item.values())


def test_list_skill_index_missing_name_uses_stem(tmp_path):
    _write(tmp_path, "bad.md", "---\ndescription: 缺 name\n---\n正文")
    idx = skills.list_skill_index([str(tmp_path)])
    assert idx[0]["name"] == "bad"  # 缺 name 不再整个丢掉（lint 负责提醒补 description/name）


def test_list_skill_index_missing_dir_returns_empty(tmp_path):
    assert skills.list_skill_index([str(tmp_path / "nope")]) == []


def test_load_skill_body_hit_and_miss(tmp_path):
    _write(tmp_path, "world-interview.md", SKILL_A)
    body = skills.load_skill_body("world-interview", [str(tmp_path)])
    assert body is not None and "不深挖支线" in body
    assert skills.load_skill_body("does-not-exist", [str(tmp_path)]) is None


def test_load_skill_body_rejects_path_traversal(tmp_path):
    (tmp_path.parent / "secret.md").write_text("---\nname: secret\n---\nleak", encoding="utf-8")
    assert skills.load_skill_body("../secret", [str(tmp_path)]) is None
    assert skills.load_skill_body("a/b", [str(tmp_path)]) is None


def test_render_skill_index_contains_meta_not_body(tmp_path):
    _write(tmp_path, "world-interview.md", SKILL_A)
    out = skills.render_skill_index([str(tmp_path)])
    assert "world-interview" in out
    assert "用户要建世界观时加载的访谈引导。" in out
    assert "不深挖支线" not in out  #Text is not indexed


def test_render_skill_index_empty_when_no_skills(tmp_path):
    assert skills.render_skill_index([str(tmp_path)]) == ""


def test_package_skill_indexed_and_body_loaded(tmp_path):
    pkg = tmp_path / "plot-extension"
    pkg.mkdir()
    (pkg / "skill.md").write_text(
        "---\nname: plot-extension\ndescription: 加桥段时加载\n---\n\n正文：先 list_plugins。",
        encoding="utf-8",
    )
    idx = skills.list_skill_index([str(tmp_path)])
    item = next(i for i in idx if i["name"] == "plot-extension")
    assert item["name"] == "plot-extension" and item["description"] == "加桥段时加载"
    body = skills.load_skill_body("plot-extension", [str(tmp_path)])
    assert body is not None and "先 list_plugins" in body


def test_flat_and_package_coexist(tmp_path):
    (tmp_path / "world-interview.md").write_text(
        "---\nname: world-interview\ndescription: 访谈\n---\n正文A", encoding="utf-8")
    pkg = tmp_path / "plot-extension"
    pkg.mkdir()
    (pkg / "skill.md").write_text(
        "---\nname: plot-extension\ndescription: 桥段\n---\n正文B", encoding="utf-8")
    names = {s["name"] for s in skills.list_skill_index([str(tmp_path)])}
    assert names == {"world-interview", "plot-extension"}


def test_collect_skill_tools_gathers_package_tools(tmp_path):
    pkg = tmp_path / "demo-skill"
    pkg.mkdir()
    (pkg / "interface.py").write_text(
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def demo_tool() -> str:\n"
        "    '''演示工具。'''\n"
        "    return 'ok'\n"
        "TOOLS = [demo_tool]\n",
        encoding="utf-8",
    )
    tools = skills.collect_skill_tools(str(tmp_path))
    assert any(getattr(t, "name", "") == "demo_tool" for t in tools)


def test_collect_skill_tools_skips_broken_interface(tmp_path):
    pkg = tmp_path / "bad-skill"
    pkg.mkdir()
    (pkg / "interface.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    assert skills.collect_skill_tools(str(tmp_path)) == []  #Bad packets are skipped and not thrown


def test_collect_skill_tools_no_dir(tmp_path):
    assert skills.collect_skill_tools(str(tmp_path / "nope")) == []


def test_collect_skill_tools_module_filter_skips(tmp_path):
    pkg = tmp_path / "webby"
    pkg.mkdir()
    (pkg / "interface.py").write_text(
        "from langchain_core.tools import tool\n"
        "REQUIRES_WEB = True\n"
        "@tool\n"
        "def t() -> str:\n    '''d'''\n    return 'x'\n"
        "TOOLS = [t]\n",
        encoding="utf-8",
    )
    #Filter out packets that require networking → tool is empty
    tools = skills.collect_skill_tools(
        str(tmp_path), module_filter=lambda m: not getattr(m, "REQUIRES_WEB", False)
    )
    assert tools == []
    #No filtering → Receive the tool
    assert len(skills.collect_skill_tools(str(tmp_path))) == 1


SKILL_EXT = """---
name: example-bridges
description: 合成测试数据用的扩展 skill 菜单，不对应任何具体 content pack。
kind: plot-extension
---

正文：MARKER-01 示例正文……
"""


def test_list_skill_index_emits_kind(tmp_path):
    _write(tmp_path, "example-bridges.md", SKILL_EXT)
    item = next(i for i in skills.list_skill_index([str(tmp_path)]) if i["name"] == "example-bridges")
    assert item["kind"] == "plot-extension"


def test_render_skill_index_excludes_plot_extension(tmp_path):
    """
The plot-extension class skill does not enter the global resident index (it is only dynamically disclosed in the skeleton phase)."""
    _write(tmp_path, "world-interview.md", SKILL_A)
    _write(tmp_path, "example-bridges.md", SKILL_EXT)
    out = skills.render_skill_index([str(tmp_path)])
    assert "world-interview" in out         #Ordinary skills are in the global index
    assert "example-bridges" not in out     #The extended skill is not in the global index


def test_render_plot_extension_menu_lists_only_extensions(tmp_path):
    _write(tmp_path, "world-interview.md", SKILL_A)        #Ordinary skill, shouldn’t appear
    _write(tmp_path, "example-bridges.md", SKILL_EXT)     #Expand skill, should appear
    menu = skills.render_plot_extension_menu([str(tmp_path)])
    assert "example-bridges" in menu
    assert "合成测试数据" in menu              #from description
    assert "world-interview" not in menu      #Ordinary skills are not mixed into the extended menu
    assert "MARKER-01" not in menu               #Still contains only metadata and no text


def test_render_plot_extension_menu_empty_when_none(tmp_path):
    _write(tmp_path, "world-interview.md", SKILL_A)
    assert skills.render_plot_extension_menu([str(tmp_path)]) == ""


def test_expand_skill_placeholders_injects_extension_menu(tmp_path):
    _write(tmp_path, "example-bridges.md", SKILL_EXT)
    body = "架构步骤……\n{{PLOT_EXTENSIONS}}\n继续扩写。"
    out = skills.expand_skill_placeholders(body, [str(tmp_path)])
    assert "{{PLOT_EXTENSIONS}}" not in out    #Placeholders are replaced
    assert "example-bridges" in out           #Dynamically integrated into the expanded menu


def test_expand_skill_placeholders_noop_without_token(tmp_path):
    body = "没有占位符的正文"
    assert skills.expand_skill_placeholders(body, [str(tmp_path)]) == body


def test_expand_skill_placeholders_direction_lens_fallback_to_baseline(tmp_path, monkeypatch):
    from context import content_packs as cp

    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path / "empty")
    cp.reload_content_packs()
    try:
        body = "前置文字，{{DIRECTION_GUIDANCE}}调工具。段落：{{LENS_GUIDANCE}}，调工具。"
        out = skills.expand_skill_placeholders(body, [str(tmp_path)])
        assert "{{DIRECTION_GUIDANCE}}" not in out
        assert "{{LENS_GUIDANCE}}" not in out
        assert skills._DEFAULT_DIRECTION_GUIDANCE in out
        assert skills._DEFAULT_LENS_GUIDANCE in out
    finally:
        cp.reload_content_packs()


def test_expand_skill_placeholders_direction_lens_use_pack_override(tmp_path, monkeypatch):
    import textwrap

    from context import content_packs as cp

    pack_dir = tmp_path / "fixture_pack"
    pack_dir.mkdir()
    (pack_dir / "hook.py").write_text(textwrap.dedent('''
        from context.content_packs import ContentPack

        CONTENT_PACK = ContentPack(
            chapter_direction_guidance="SENTINEL方向引导",
            stage_lens_guidance="SENTINEL分镜引导",
        )
    '''), encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path)
    cp.reload_content_packs()
    try:
        body = "{{DIRECTION_GUIDANCE}}／{{LENS_GUIDANCE}}"
        out = skills.expand_skill_placeholders(body, [str(tmp_path)])
        assert out == "SENTINEL方向引导／SENTINEL分镜引导"
    finally:
        cp.reload_content_packs()


def test_expand_skill_placeholders_plot_interview_fallback_to_baseline(tmp_path, monkeypatch):
    from context import content_packs as cp

    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path / "empty")
    cp.reload_content_packs()
    try:
        body = "core_xp（{{CORE_XP_GUIDANCE}}）。段落（{{STAGE_DESCRIPTION_GUIDANCE}}；其它）。"
        out = skills.expand_skill_placeholders(body, [str(tmp_path)])
        assert "{{CORE_XP_GUIDANCE}}" not in out
        assert "{{STAGE_DESCRIPTION_GUIDANCE}}" not in out
        assert skills._DEFAULT_CORE_XP_GUIDANCE in out
        assert skills._DEFAULT_STAGE_DESCRIPTION_GUIDANCE in out
    finally:
        cp.reload_content_packs()


def test_expand_skill_placeholders_plot_interview_use_pack_override(tmp_path, monkeypatch):
    import textwrap

    from context import content_packs as cp

    pack_dir = tmp_path / "fixture_pack"
    pack_dir.mkdir()
    (pack_dir / "hook.py").write_text(textwrap.dedent('''
        from context.content_packs import ContentPack

        CONTENT_PACK = ContentPack(
            plot_core_xp_guidance="SENTINEL章纲卖点引导",
            plot_stage_guidance="SENTINEL场景概述引导",
        )
    '''), encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path)
    cp.reload_content_packs()
    try:
        body = "{{CORE_XP_GUIDANCE}}／{{STAGE_DESCRIPTION_GUIDANCE}}"
        out = skills.expand_skill_placeholders(body, [str(tmp_path)])
        assert out == "SENTINEL章纲卖点引导／SENTINEL场景概述引导"
    finally:
        cp.reload_content_packs()


def test_address_self_ref_design_skill_exists_and_has_worked_example():
    from engine.setup_chat.skills import load_skill_body
    from utils.paths import SETUP_CHAT_SKILLS_DIR

    body = load_skill_body("address-self-ref-design", [SETUP_CHAT_SKILLS_DIR])
    assert body is not None
    assert "address_ref" in body and "self_ref" in body
    assert "```json" in body
    assert '"self_ref"' in body and '"sliders"' in body
    assert "门控" in body or "档位" in body


def test_skeleton_expansion_skill_is_architecture_only():
    """Architecture skill original text: Retain segment-by-section arrangement, and no longer embed detailed refinement/list_plugins."""
    from engine.setup_chat.skills import load_skill_body
    from utils.paths import SETUP_CHAT_SKILLS_DIR

    body = load_skill_body("skeleton-expansion", [SETUP_CHAT_SKILLS_DIR])
    assert body is not None
    assert "read_skeleton_seed" in body and "write_chapter_skeleton" in body
    assert "present_choices" in body
    assert "逐段" in body
    assert "load_skill" in body                #3b loads plot-extension skills (e.g. example-bridges) via load_skill
    assert "list_plugins" not in body          #Old plugin tools have been retired


def test_skeleton_skill_scripts_chapter_done_terminal_and_scope_boundary():
    """
The entire chapter is expanded with an explicit final state option (block overwrite blank), and dialogue extensions are referenced generically (not by hardcoded skill id).

    Root cause regression: "Continue to the next paragraph" after the last paragraph, there is no next paragraph, the prompt has no scripted final state, and the agent improvises.
    Revision method = final state present_choices points to refined revision / chapter-done stop."""

    from engine.setup_chat.skills import load_skill_body
    from utils.paths import SETUP_CHAT_SKILLS_DIR

    body = load_skill_body("skeleton-expansion", [SETUP_CHAT_SKILLS_DIR])
    assert body is not None
    #Final state: an explicit branch after the entire chapter has been expanded, leading to refinement
    assert "全部扩完" in body or "最后一段" in body
    assert "含台词" in body or "台词设计" in body
    #Scope: dialogue is a per-stage 3b extension, not a post-chapter follow-up phase
    assert "构建期到此为止" in body
    #3b must not hardcode extension skill names (registry-driven menu)
    assert "不点名" in body or "不预设" in body


def test_skeleton_skill_enforces_storyboard_first_each_stage():
    """
Storyboarding must be the mandatory first step of each segment, and each segment must be replayed - to prevent the return of "only stage1 is storyboarded"."""
    from engine.setup_chat.skills import load_skill_body
    from utils.paths import SETUP_CHAT_SKILLS_DIR

    body = load_skill_body("skeleton-expansion", [SETUP_CHAT_SKILLS_DIR])
    assert body is not None
    assert "3a" in body and "3b" in body          #Explicit numbering in steps
    assert "每段" in body                          #Each segment needs to be re-storyboarded
    #When continuing to the next paragraph, explicitly return to the storyboard (3a) instead of just "ask again"
    assert "从 3a" in body or "回到 3a" in body or "3a 分镜重新" in body


def test_scenario_bridges_is_plot_extension_kind(tmp_path):
    """kind=plot-extension 的 skill 会被正确分类且能取到正文（合成 skill，不依赖具体 content pack）。"""
    from engine.setup_chat.skills import list_skill_index, load_skill_body

    _write(tmp_path, "example-bridges.md", """---
name: example-bridges
description: 可织入剧情的合成测试数据，扩写某段想加特殊情景时加载。
metadata:
  kind: plot-extension
---

真实条目：MARKER-01。
""")
    dirs = [str(tmp_path)]
    item = next(i for i in list_skill_index(dirs) if i["name"] == "example-bridges")
    assert item["kind"] == "plot-extension"
    body = load_skill_body("example-bridges", dirs)
    assert body is not None and "MARKER-01" in body


def test_plot_extension_not_in_global_index():
    """
plot-extension does not enter the global resident index (to avoid contaminating top-level entry skills)."""
    from engine.setup_chat.skills import render_skill_index
    from utils.paths import SETUP_CHAT_SKILLS_DIR

    out = render_skill_index([SETUP_CHAT_SKILLS_DIR])
    assert "skeleton-expansion" in out      #Normal entrance skill is in
    assert "example-bridges" not in out     #The extended skill is not in the global index


def test_construction_plan_skill_has_orchestration():
    """world/schema/character/plot/timeline are code-pipeline driven — no
    JSON-plan tools."""
    from engine.setup_chat.skills import load_skill_body
    from utils.paths import SETUP_CHAT_SKILLS_DIR
    body = load_skill_body("construction-plan", [SETUP_CHAT_SKILLS_DIR])
    assert body is not None
    assert "write_construction_plan" not in body
    assert "read_construction_plan" not in body
    assert "activate_repair_plan" not in body


def test_construction_plan_skill_has_four_step_roadmap_pointing_at_dedicated_skills():
    """world/character/plot each have their own dedicated skill; timeline is engine-driven."""
    from engine.setup_chat.skills import load_skill_body
    from utils.paths import SETUP_CHAT_SKILLS_DIR
    body = load_skill_body("construction-plan", [SETUP_CHAT_SKILLS_DIR])
    assert body is not None
    for kw in ("world", "character", "plot_chapter", "timeline"):
        assert kw in body
    for skill in ("world-interview", "character-interview", "plot-interview"):
        assert skill in body
    assert "schema-interview" not in body
    assert "timeline-derivation" not in body
    assert "write_character_archive" in body


def test_construction_plan_skill_forbids_migrated_kinds_in_json_plan():
    """world/character/plot/timeline must use direct tool calls on the
    code-defined world_pipeline — the card must not reference retired JSON-plan tools."""
    from engine.setup_chat.skills import load_skill_body
    from utils.paths import SETUP_CHAT_SKILLS_DIR
    body = load_skill_body("construction-plan", [SETUP_CHAT_SKILLS_DIR])
    assert body is not None
    assert "write_construction_plan" not in body
    assert "read_construction_plan" not in body
    assert "直接" in body or "world 建设管道" in body
    for tool in ("set_world_background", "add_character", "write_character_archive"):
        assert tool in body


SKILL_YAML_STD = """---
name: demo
description: >-
  第一行
  第二行
metadata:
  kind: plot-extension
---

标准格式正文。
"""


def test_parse_skill_yaml_multiline_and_metadata_namespace():
    meta, body = skills._parse_skill(SKILL_YAML_STD)
    assert meta["description"] == "第一行 第二行"
    assert meta["kind"] == "plot-extension"
    assert body == "标准格式正文。"


def test_parse_skill_legacy_flat_keys_still_work():
    text = "---\nname: demo\nkind: plot-extension\n---\n正文"
    meta, _ = skills._parse_skill(text)
    assert meta["kind"] == "plot-extension"


def test_parse_skill_broken_yaml_falls_back_to_full_body():
    text = "---\nname: [未闭合\n---\n正文"
    meta, body = skills._parse_skill(text)
    assert meta == {}
    assert "正文" in body  # 容错：整段当正文，不丢内容


def test_uppercase_skill_md_recognized(tmp_path):
    pkg = tmp_path / "demo"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n正文U", encoding="utf-8")
    idx = skills.list_skill_index([str(tmp_path)])
    assert idx and idx[0]["name"] == "demo"
    assert skills.load_skill_body("demo", [str(tmp_path)]) == "正文U"


def test_name_authority_is_dirname(tmp_path):
    pkg = tmp_path / "real-name"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text("---\nname: other-name\ndescription: d\n---\n正文", encoding="utf-8")
    idx = skills.list_skill_index([str(tmp_path)])
    assert idx[0]["name"] == "real-name"                                   # 目录名生效
    assert skills.load_skill_body("real-name", [str(tmp_path)]) is not None  # 按目录名可取
    assert skills.load_skill_body("other-name", [str(tmp_path)]) is None     # frontmatter 名取不到


def test_multi_dir_merge_builtin_wins(tmp_path):
    builtin = tmp_path / "builtin"
    imported = tmp_path / "imported"
    builtin.mkdir(); imported.mkdir()
    (builtin / "dup.md").write_text("---\ndescription: 内建版\n---\n内建正文", encoding="utf-8")
    (imported / "dup.md").write_text("---\ndescription: 导入版\n---\n导入正文", encoding="utf-8")
    (imported / "extra.md").write_text("---\ndescription: 只在导入\n---\n导入独有", encoding="utf-8")
    idx = skills.list_skill_index([str(builtin), str(imported)])
    by_name = {it["name"]: it for it in idx}
    assert by_name["dup"]["description"] == "内建版"     # 同名内建优先
    assert by_name["dup"]["source"] == "builtin"
    assert by_name["extra"]["source"] == "imported"
    assert skills.load_skill_body("dup", [str(builtin), str(imported)]) == "内建正文"
    assert skills.load_skill_body("extra", [str(builtin), str(imported)]) == "导入独有"


def test_multi_dir_missing_imported_dir_tolerated(tmp_path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    (builtin / "a.md").write_text("---\ndescription: d\n---\n正文", encoding="utf-8")
    idx = skills.list_skill_index([str(builtin), str(tmp_path / "nope")])
    assert [it["name"] for it in idx] == ["a"]  # 导入目录不存在 → 静默跳过


def test_setup_chat_skill_dirs_order():
    """内建目录永远第一、导入目录永远最后；中间是当前启用的内容包贡献目录（真实仓库里
    某内容包默认启用，会贡献至少一个 setup_chat_skills 子目录，数量不作硬编码假设）。"""
    from utils.paths import IMPORTED_SKILLS_DIR, SETUP_CHAT_SKILLS_DIR

    dirs = skills.setup_chat_skill_dirs()
    assert dirs[0] == SETUP_CHAT_SKILLS_DIR
    assert dirs[-1] == IMPORTED_SKILLS_DIR


def test_setup_chat_skill_dirs_includes_content_pack_contributions(monkeypatch):
    from utils.paths import IMPORTED_SKILLS_DIR, SETUP_CHAT_SKILLS_DIR

    monkeypatch.setattr(
        "context.content_packs.contributed_dirs",
        lambda attr: ["/fake/pack/setup_chat_skills"] if attr == "setup_chat_skill_dirs" else [],
    )
    assert skills.setup_chat_skill_dirs() == [
        SETUP_CHAT_SKILLS_DIR, "/fake/pack/setup_chat_skills", IMPORTED_SKILLS_DIR,
    ]


def _mk_pkg_with_ref(tmp_path):
    pkg = tmp_path / "guide"
    (pkg / "references").mkdir(parents=True)
    (pkg / "SKILL.md").write_text("---\ndescription: d\n---\n正文见 references/detail.md", encoding="utf-8")
    (pkg / "references" / "detail.md").write_text("引用正文内容", encoding="utf-8")
    return pkg


def test_load_reference_file(tmp_path):
    _mk_pkg_with_ref(tmp_path)
    out = skills.load_skill_body("guide/references/detail.md", [str(tmp_path)])
    assert out == "引用正文内容"  # 原样返回，不做 frontmatter 解析


def test_load_reference_rejects_traversal_and_bad_ext(tmp_path):
    _mk_pkg_with_ref(tmp_path)
    (tmp_path / "secret.md").write_text("leak", encoding="utf-8")
    dirs = [str(tmp_path)]
    assert skills.load_skill_body("guide/references/../../secret.md", dirs) is None  # 穿越
    assert skills.load_skill_body("guide/references/x.py", dirs) is None             # 扩展名白名单外
    assert skills.load_skill_body("guide/assets/detail.md", dirs) is None            # 只认 references/
    assert skills.load_skill_body("guide/references/missing.md", dirs) is None       # 不存在


def _write_iface(pkg, tool_name):
    pkg.mkdir()
    (pkg / "interface.py").write_text(
        "from langchain_core.tools import tool\n"
        f"@tool\ndef {tool_name}() -> str:\n    '''演示工具。'''\n    return 'ok'\n"
        f"TOOLS = [{tool_name}]\n",
        encoding="utf-8",
    )


def test_collect_skill_tools_skips_builtin_name_conflict(tmp_path):
    _write_iface(tmp_path / "pkg-a", "load_skill")   # 撞内置工具名
    _write_iface(tmp_path / "pkg-b", "fresh_tool")
    tools = skills.collect_skill_tools(str(tmp_path), existing_tool_names={"load_skill"})
    names = [getattr(t, "name", "") for t in tools]
    assert names == ["fresh_tool"]  # 撞名的被跳过，不撞的照收


def test_collect_skill_tools_skips_cross_package_conflict(tmp_path):
    _write_iface(tmp_path / "pkg-a", "same_tool")
    _write_iface(tmp_path / "pkg-b", "same_tool")   # 两包同名工具
    tools = skills.collect_skill_tools(str(tmp_path))
    assert len(tools) == 1  # 目录序在前的胜出，后者跳过


def test_collect_skill_tools_allows_asset_sibling_import(tmp_path):
    pkg = tmp_path / "asset-skill"
    pkg.mkdir()
    (pkg / "assets").mkdir()
    (pkg / "assets" / "helper.py").write_text(
        "def double(x):\n    return x * 2\n",
        encoding="utf-8",
    )
    (pkg / "interface.py").write_text(
        "from langchain_core.tools import tool\n"
        "from helper import double\n"
        "@tool\n"
        "def doubled(x: int) -> str:\n"
        "    '''演示 sibling import。'''\n"
        "    return str(double(x))\n"
        "TOOLS = [doubled]\n",
        encoding="utf-8",
    )
    tools = skills.collect_skill_tools(str(tmp_path))
    names = [getattr(t, "name", "") for t in tools]
    assert "doubled" in names


def test_collect_single_skill_tools_loads_named_package(tmp_path):
    pkg = tmp_path / "demo-skill"
    pkg.mkdir()
    (pkg / "interface.py").write_text(
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def demo_tool() -> str:\n"
        "    '''演示工具。'''\n"
        "    return 'ok'\n"
        "TOOLS = [demo_tool]\n",
        encoding="utf-8",
    )
    tools = skills.collect_single_skill_tools(str(tmp_path), "demo-skill")
    assert [getattr(t, "name", "") for t in tools] == ["demo_tool"]


def test_collect_single_skill_tools_no_interface_returns_empty(tmp_path):
    pkg = tmp_path / "text-only-skill"
    pkg.mkdir()
    assert skills.collect_single_skill_tools(str(tmp_path), "text-only-skill") == []


def test_collect_single_skill_tools_broken_interface_returns_empty(tmp_path):
    pkg = tmp_path / "bad-skill"
    pkg.mkdir()
    (pkg / "interface.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    assert skills.collect_single_skill_tools(str(tmp_path), "bad-skill") == []


def test_collect_single_skill_tools_unknown_name_returns_empty(tmp_path):
    assert skills.collect_single_skill_tools(str(tmp_path), "nope") == []
