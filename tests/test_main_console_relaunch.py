"""Tests for main.py's tauri:dev interactive-console relaunch trigger."""
import os

from main import _relaunch_command, _should_relaunch_for_console


def _call(**overrides) -> bool:
    defaults = dict(
        dev=False,
        distributed=False,
        sequenced=False,
        platform="win32",
        already_relaunched=False,
        stdin_isatty=False,
        stdout_isatty=False,
    )
    defaults.update(overrides)
    return _should_relaunch_for_console(**defaults)


def test_triggers_for_dev_flag_when_not_a_real_tty() -> None:
    assert _call(dev=True) is True


def test_triggers_for_distributed_flag_when_not_a_real_tty() -> None:
    assert _call(distributed=True) is True


def test_triggers_for_sequenced_flag_when_not_a_real_tty() -> None:
    assert _call(sequenced=True) is True


def test_does_not_trigger_for_bare_combined_mode() -> None:
    """Bare combined mode (no dev/distributed/sequenced) is exactly what the
    packaged production Tauri sidecar invokes -- must never pop a console."""
    assert _call(dev=False, distributed=False, sequenced=False) is False


def test_does_not_trigger_when_already_relaunched() -> None:
    assert _call(dev=True, already_relaunched=True) is False


def test_does_not_trigger_with_a_real_tty() -> None:
    assert _call(dev=True, stdin_isatty=True, stdout_isatty=True) is False


def test_does_not_trigger_with_partial_tty() -> None:
    """Both stdin and stdout must be real ttys -- one piped is enough to trigger."""
    assert _call(dev=True, stdin_isatty=True, stdout_isatty=False) is True
    assert _call(dev=True, stdin_isatty=False, stdout_isatty=True) is True


def test_does_not_trigger_on_non_windows() -> None:
    assert _call(dev=True, platform="linux") is False


def test_relaunch_command_reruns_run_py_with_original_argv() -> None:
    cmd = _relaunch_command(
        root=r"C:\project", executable=r"C:\venv\python.exe", argv=["--dev", "--no-browser"]
    )
    assert cmd == [
        r"C:\venv\python.exe",
        os.path.join(r"C:\project", "run.py"),
        "--dev",
        "--no-browser",
    ]


def test_relaunch_command_passes_through_empty_argv() -> None:
    cmd = _relaunch_command(root=r"C:\project", executable=r"C:\venv\python.exe", argv=[])
    assert cmd == [r"C:\venv\python.exe", os.path.join(r"C:\project", "run.py")]
