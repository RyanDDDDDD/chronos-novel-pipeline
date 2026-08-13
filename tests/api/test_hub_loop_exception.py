from unittest.mock import MagicMock

import api.hub as hub_module
from api.hub import _log_loop_exception


def test_connection_reset_is_silently_dropped(monkeypatch):
    """dev_console's health probe reconnects constantly and Windows' ProactorEventLoop
    surfaces each one as a ConnectionResetError during transport cleanup -- confirmed
    benign (never accompanies a real generation-stream interruption), so this must not
    write anything to server.log at all, not even at DEBUG (the sink itself is
    configured at DEBUG level, so logging it there still floods the file)."""
    mock_logger = MagicMock()
    monkeypatch.setattr(hub_module, "logger", mock_logger)

    context = {
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
        "exception": ConnectionResetError("[WinError 10054] forcibly closed"),
    }
    _log_loop_exception(MagicMock(), context)

    mock_logger.debug.assert_not_called()
    mock_logger.opt.assert_not_called()
    mock_logger.error.assert_not_called()


def test_other_loop_exceptions_still_logged_as_error(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(hub_module, "logger", mock_logger)

    exc = RuntimeError("something genuinely unexpected")
    context = {"message": "Exception in callback SomeOtherThing()", "exception": exc}
    _log_loop_exception(MagicMock(), context)

    mock_logger.opt.assert_called_once_with(exception=exc)
    mock_logger.opt.return_value.error.assert_called_once()


def test_recursion_error_logs_raw_traceback_without_diagnose(monkeypatch):
    mock_logger = MagicMock()
    monkeypatch.setattr(hub_module, "logger", mock_logger)

    exc = RecursionError("maximum recursion depth exceeded while calling a Python object")
    context = {
        "message": "Exception in callback <_asyncio.TaskStepMethWrapper object>()",
        "exception": exc,
    }
    _log_loop_exception(MagicMock(), context)

    mock_logger.opt.assert_not_called()
    mock_logger.error.assert_called_once()
    logged = mock_logger.error.call_args[0][0]
    assert "RecursionError" in logged
    assert "raw traceback dump" in logged
