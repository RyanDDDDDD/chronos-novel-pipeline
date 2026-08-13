"""Tests for main.py's centralized startup-port resolution."""
import socket

import pytest

from main import _find_free_port


def _occupy(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    return s


def test_returns_start_port_when_free() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()

    assert _find_free_port(free_port) == free_port


def test_increments_past_occupied_port() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    base_port = probe.getsockname()[1]
    probe.close()

    occupied = _occupy(base_port)
    try:
        expected = base_port + 1
        while True:
            try:
                next_free = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                next_free.bind(("127.0.0.1", expected))
                next_free.close()
                break
            except OSError:
                expected += 1
        assert _find_free_port(base_port) == expected
    finally:
        occupied.close()


def test_skips_reserved_port() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    base_port = probe.getsockname()[1]
    probe.close()

    occupied = _occupy(base_port)
    try:
        result = _find_free_port(base_port, reserved=frozenset({base_port + 1}))
        assert result == base_port + 2
    finally:
        occupied.close()


def test_raises_when_no_port_available_within_attempts() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    base_port = probe.getsockname()[1]
    probe.close()

    occupied_a = _occupy(base_port)
    occupied_b = _occupy(base_port + 1)
    try:
        with pytest.raises(RuntimeError):
            _find_free_port(base_port, max_attempts=2)
    finally:
        occupied_a.close()
        occupied_b.close()
