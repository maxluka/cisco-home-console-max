"""Minimal AMI client that mirrors house state into Asterisk BLF lamps.

Each lamp is a `Custom:` device state (`Custom:home_room_kitchen` and so on)
that the Asterisk dialplan exposes as a hint; the phones subscribe to the
hints, and this client moves the states underneath them.  Nothing more of AMI
is used than Login, Command and Logoff.
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass

from services.home import BlfState

logger = logging.getLogger(__name__)


class AsteriskBridgeError(RuntimeError):
    """A user-safe failure while updating Asterisk device states."""


@dataclass(frozen=True)
class AsteriskManagerSettings:
    host: str
    username: str
    secret: str
    port: int = 5038

    @property
    def label(self) -> str:
        return f"{self.host}:{self.port}"


class AsteriskBlfBridge:
    def __init__(self, settings: AsteriskManagerSettings) -> None:
        self._settings = settings

    @property
    def settings(self) -> AsteriskManagerSettings:
        return self._settings

    @staticmethod
    def _action(**fields: str) -> bytes:
        return ("".join(f"{key}: {value}\r\n" for key, value in fields.items()) + "\r\n").encode()

    @staticmethod
    def _read_until(connection: socket.socket, terminator: bytes) -> str:
        chunks: list[bytes] = []
        while terminator not in b"".join(chunks):
            chunk = connection.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")

    def sync(self, states: list[BlfState], prefix: str = "home_scene") -> None:
        """Mirror one family of states into `Custom:<prefix>_<key>` devstates."""
        if not states:
            return
        self.run(
            [
                f"devstate change Custom:{prefix}_{state.key} {state.asterisk_state}"
                for state in states
            ]
        )

    def run(self, commands: list[str]) -> list[str]:
        """Run CLI commands down one connection and return what each said."""
        settings = self._settings
        replies: list[str] = []
        try:
            with socket.create_connection((settings.host, settings.port), timeout=5) as connection:
                # The AMI banner is a single line, not a complete action
                # response.  Waiting for a header separator here would always
                # consume the socket timeout before the Login action is sent.
                connection.recv(4096)
                connection.sendall(
                    self._action(
                        Action="Login",
                        Username=settings.username,
                        Secret=settings.secret,
                        # Without this, Asterisk pushes asynchronous events
                        # down the same socket -- including the
                        # DeviceStateChange each command below causes -- and
                        # they interleave with the replies we want to read.
                        Events="off",
                    )
                )
                if "Response: Success" not in self._read_until(connection, b"\r\n\r\n"):
                    raise AsteriskBridgeError("Asterisk AMI login was rejected.")
                for command in commands:
                    connection.sendall(self._action(Action="Command", Command=command))
                    reply = self._read_until(connection, b"\r\n\r\n")
                    if not self._command_succeeded(reply):
                        raise AsteriskBridgeError("Asterisk refused a command.")
                    replies.append(reply)
                connection.sendall(self._action(Action="Logoff"))
        except (OSError, TimeoutError) as exc:
            raise AsteriskBridgeError("Asterisk is unreachable.") from exc
        return replies

    @staticmethod
    def _command_succeeded(reply: str) -> bool:
        """Accept either AMI dialect for `Action: Command`.

        Asterisk 11 answers `Response: Follows`, prints the CLI output raw and
        closes with `--END COMMAND--`; 12 and newer answer `Response: Success`
        and fold the output into `Output:` headers.
        """
        return "Response: Follows" in reply or "Response: Success" in reply
