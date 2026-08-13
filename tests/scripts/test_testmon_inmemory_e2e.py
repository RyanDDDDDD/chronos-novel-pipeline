"""End-to-end regression: the in-memory testmon backend must select exactly the same set
of tests to re-run as vanilla direct-disk testmon does. Spins up two tiny scratch pytest
projects (one with the patch wired in via a copied conftest.py, one without) and compares
which tests get selected after an unrelated-looking-but-checksum-changing edit.
See docs/superpowers/specs/2026-08-12-testmon-inmemory-backend-design.md section 5."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path


def _pytest_exe() -> str:
    venv_dir = Path(sys.executable).parent
    candidate = venv_dir / ("pytest.exe" if sys.platform == "win32" else "pytest")
    return str(candidate)


def _make_scratch_project(base: Path, *, patched: bool) -> Path:
    project = base / ("patched" if patched else "control")
    project.mkdir()
    (project / "mod.py").write_text("def helper():\n    return 1\n")
    (project / "test_a.py").write_text("def test_a():\n    assert 1 == 1\n")
    (project / "test_b.py").write_text(
        "from mod import helper\n\n\ndef test_b():\n    assert helper() == 1\n"
    )
    if patched:
        real_module = Path(__file__).parent.parent / "_testmon_inmemory.py"
        shutil.copy(real_module, project / "_testmon_inmemory.py")
        (project / "conftest.py").write_text(
            "import _testmon_inmemory\n\n\n"
            "def pytest_sessionfinish(session, exitstatus):\n"
            "    _testmon_inmemory.flush_to_disk()\n"
        )
    return project


def _run_selected_tests(pytest_exe: str, scratch_dir: Path) -> set[str]:
    # --color=no: without it, pytest emits ANSI codes even through a captured pipe whenever
    # the outer environment forces color (e.g. FORCE_COLOR=1) -- those codes land between the
    # nodeid and "PASSED", silently breaking the regex below and making every test look
    # deselected regardless of what testmon actually did.
    result = subprocess.run(
        [pytest_exe, "--testmon", "--color=no", "-v"],
        cwd=scratch_dir, capture_output=True, text=True, timeout=60,
    )
    return set(re.findall(r"^(test_\w+\.py::test_\w+) PASSED", result.stdout, re.MULTILINE))


def test_inmemory_backend_selects_same_tests_as_direct_disk(tmp_path):
    pytest_exe = _pytest_exe()
    control = _make_scratch_project(tmp_path, patched=False)
    patched = _make_scratch_project(tmp_path, patched=True)

    for project in (control, patched):
        subprocess.run(
            [pytest_exe, "--testmon", "-q"],
            cwd=project, capture_output=True, text=True, timeout=60,
        )

    # Change mod.py's checksum without changing its behavior -- test_b depends on it,
    # test_a doesn't, so only test_b should be selected on the next run.
    for project in (control, patched):
        (project / "mod.py").write_text("def helper():\n    return 1 + 0  # touched\n")

    control_selected = _run_selected_tests(pytest_exe, control)
    patched_selected = _run_selected_tests(pytest_exe, patched)

    assert control_selected == {"test_b.py::test_b"}
    assert patched_selected == control_selected
