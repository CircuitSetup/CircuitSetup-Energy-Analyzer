from __future__ import annotations

import sys

import pytest

try:
    import pytest_socket
except ImportError:  # pragma: no cover - fallback CI does not install this plugin.
    pytest_socket = None  # type: ignore[assignment]


def _disable_socket_noop(*args: object, **kwargs: object) -> None:
    return None


if pytest_socket is not None and sys.platform == "win32":
    pytest_socket.disable_socket = _disable_socket_noop  # type: ignore[assignment]
    pytest_socket.enable_socket()


@pytest.hookimpl(trylast=True)
def pytest_runtest_setup() -> None:
    if pytest_socket is not None and sys.platform == "win32":
        pytest_socket.enable_socket()
