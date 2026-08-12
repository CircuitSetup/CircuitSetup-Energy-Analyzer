from __future__ import annotations

import socket
import sys

import pytest

try:
    import pytest_socket
except ImportError:  # pragma: no cover - fallback CI does not install this plugin.
    pytest_socket = None  # type: ignore[assignment]


def _disable_socket_noop(*args: object, **kwargs: object) -> None:
    return None


def _patch_windows_proactor_peer_reset() -> None:
    """Finish asyncio transport cleanup after a browser closes a peer socket."""

    if sys.platform != "win32":
        return
    from asyncio.proactor_events import _ProactorSocketTransport

    def call_connection_lost(self: object, exc: BaseException | None) -> None:
        if self._called_connection_lost:
            return
        try:
            self._protocol.connection_lost(exc)
        finally:
            # CPython documents ERROR_NETNAME_DELETED here when a peer closes
            # while the Proactor transport is shutting down.  Chromium does
            # this after a successful browser test; complete the remaining
            # stdlib cleanup but retain every other socket error.
            if hasattr(self._sock, "shutdown") and self._sock.fileno() != -1:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except ConnectionResetError as error:
                    if error.winerror != 10054:
                        raise
            self._sock.close()
            self._sock = None
            server = self._server
            if server is not None:
                server._detach()
                self._server = None
            self._called_connection_lost = True

    _ProactorSocketTransport._call_connection_lost = call_connection_lost


_patch_windows_proactor_peer_reset()


if pytest_socket is not None and sys.platform == "win32":
    pytest_socket.disable_socket = _disable_socket_noop  # type: ignore[assignment]
    pytest_socket.enable_socket()


@pytest.hookimpl(trylast=True)
def pytest_runtest_setup() -> None:
    if pytest_socket is not None and sys.platform == "win32":
        pytest_socket.enable_socket()
