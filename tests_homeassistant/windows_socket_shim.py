from __future__ import annotations

import sys

import pytest
import pytest_socket


def _disable_socket_noop(*args: object, **kwargs: object) -> None:
    return None


if sys.platform == "win32":
    pytest_socket.disable_socket = _disable_socket_noop  # type: ignore[assignment]
    pytest_socket.enable_socket()


@pytest.hookimpl(trylast=True)
def pytest_runtest_setup() -> None:
    if sys.platform == "win32":
        pytest_socket.enable_socket()
