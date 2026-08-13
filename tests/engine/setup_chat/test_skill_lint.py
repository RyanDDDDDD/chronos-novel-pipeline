from engine.setup_chat.skill_lint import lint_dirs


def _levels_for(findings, needle):
    return [(lv, msg) for lv, name, msg in findings if needle in name or needle in msg]


def test_lint_clean_skill_no_findings(tmp_path):
    pkg = tmp_path / "good"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text("---\nname: good\ndescription: 演示\n---\n正文", encoding="utf-8")
    assert lint_dirs([str(tmp_path)]) == []


def test_lint_reports_yaml_error_and_missing_description(tmp_path):
    (tmp_path / "bad-yaml.md").write_text("---\nname: [未闭合\n---\n正文", encoding="utf-8")
    (tmp_path / "no-desc.md").write_text("---\nname: no-desc\n---\n正文", encoding="utf-8")
    findings = lint_dirs([str(tmp_path)])
    assert any(lv == "error" for lv, msg in _levels_for(findings, "bad-yaml"))     # YAML 坏 = error
    assert any(lv == "warning" for lv, msg in _levels_for(findings, "no-desc"))    # 缺 description = warning


def test_lint_reports_name_mismatch_and_duplicate(tmp_path):
    builtin = tmp_path / "b"; imported = tmp_path / "i"
    builtin.mkdir(); imported.mkdir()
    (builtin / "real.md").write_text("---\nname: other\ndescription: d\n---\n正文", encoding="utf-8")
    (imported / "real.md").write_text("---\ndescription: 导入同名\n---\n正文", encoding="utf-8")
    findings = lint_dirs([str(builtin), str(imported)])
    assert any(lv == "warning" and "以后者为准" in msg for lv, msg in _levels_for(findings, "real"))
    assert any(lv == "error" and "同名" in msg for lv, msg in _levels_for(findings, "real"))


def test_lint_reports_stripped_capabilities(tmp_path):
    builtin = tmp_path / "b"; imported = tmp_path / "i"
    pkg = imported / "ext-skill"
    (pkg / "scripts").mkdir(parents=True)
    builtin.mkdir()
    (pkg / "SKILL.md").write_text("---\ndescription: d\n---\n正文", encoding="utf-8")
    (pkg / "scripts" / "run.sh").write_text("echo hi", encoding="utf-8")
    (pkg / "interface.py").write_text("TOOLS = []", encoding="utf-8")
    findings = lint_dirs([str(builtin), str(imported)])
    msgs = [msg for lv, name, msg in findings if name == "ext-skill"]
    assert any("不执行脚本" in m for m in msgs)      # D4：scripts/ 剥离明确告知
    assert any("不执行代码" in m for m in msgs)      # D3：导入目录 interface.py 被忽略
    assert all(lv == "warning" for lv, name, msg in findings if name == "ext-skill")  # 纯 warning 退出码 0


def test_lint_reports_builtin_broken_interface(tmp_path):
    pkg = tmp_path / "broken"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text("---\ndescription: d\n---\n正文", encoding="utf-8")
    (pkg / "interface.py").write_text("raise RuntimeError('boom')", encoding="utf-8")
    findings = lint_dirs([str(tmp_path)])
    assert any(lv == "error" for lv, name, msg in findings if name == "broken")  # 运行期工具会静默消失→error
