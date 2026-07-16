"""sim_link.py - IPC link between the UI host process and a headless sim child.

Single-window simulation (see docs/experiments/single_window_sim.md): the
launcher keeps its pygame window for the whole session; the GHDL/NVC + cocotb
subprocess runs with no display of its own and shuttles signal state through
this link instead.

Transport: ``multiprocessing.connection`` over 127.0.0.1 TCP - one mechanism
that works on Linux, Windows, and macOS alike - authenticated with a random
per-run HMAC authkey.  Both endpoints are this codebase, so messages are plain
picklable tuples ``(kind, payload)``.

Child -> host:
    ("hello", {"pid": int})
    ("state", {"led": int, "seg": int | None, "sim_ns": int, "steps": int,
               "input_seq": int, "step_ns": int, "timer_pct": float,
               "at_max": bool})
    ("bye",   {"sim_ns": int, "steps": int, "wall_s": float})

Host -> child:
    ("input", {"sw": int, "btn": int, "seq": int})
    ("speed", {"factor": float})
    ("clk",   {"half_ns": int})
    ("pause", {"on": bool})
    ("stop",  {})

``drain()`` additionally synthesizes ("eof", {}) when the peer has gone away,
so callers see process death as an ordinary message.
"""

from __future__ import annotations

import os
import secrets
import threading
from multiprocessing.connection import Client, Connection, Listener
from typing import Any, cast

Message = tuple[str, dict[str, Any]]

#: Env vars advertising the host's listener to the sim child.
LINK_PORT_ENV = "FPGA_SIM_LINK_PORT"
LINK_KEY_ENV = "FPGA_SIM_LINK_KEY"

_LOCALHOST = "127.0.0.1"


class SimLinkHost:
    """UI-process end: listen on an ephemeral local port, accept the sim child.

    ``accept()`` blocks, so it runs on a daemon thread started in
    ``__init__``; the UI keeps rendering and polls :meth:`wait_connected`.
    """

    def __init__(self) -> None:
        """Bind an ephemeral 127.0.0.1 port and start accepting in the background."""
        self._key = secrets.token_bytes(16)
        self._listener = Listener((_LOCALHOST, 0), authkey=self._key)
        self._conn: Connection | None = None
        self._accept_error: BaseException | None = None
        self._accept_thread = threading.Thread(target=self._accept, daemon=True)
        self._accept_thread.start()

    def _accept(self) -> None:
        try:
            self._conn = self._listener.accept()
        except BaseException as e:  # noqa: BLE001 - surfaced by wait_connected()
            self._accept_error = e

    def env_vars(self) -> dict[str, str]:
        """Env vars the child needs to connect (see :func:`connect_from_env`)."""
        # typeshed says address is str (the AF_UNIX/AF_PIPE shape); AF_INET is a tuple
        port = cast("tuple[str, int]", self._listener.address)[1]
        return {LINK_PORT_ENV: str(port), LINK_KEY_ENV: self._key.hex()}

    def wait_connected(self, timeout: float) -> bool:
        """Wait up to *timeout* seconds for the child; False if still pending."""
        self._accept_thread.join(timeout)
        if self._accept_error is not None:
            raise RuntimeError(f"sim link accept failed: {self._accept_error}")
        return self._conn is not None

    @property
    def conn(self) -> Connection:
        """The accepted connection (only valid after :meth:`wait_connected`)."""
        assert self._conn is not None, "call wait_connected() first"
        return self._conn

    def close(self) -> None:
        """Close the accepted connection (if any) and the listener."""
        if self._conn is not None:
            self._conn.close()
        self._listener.close()


def connect_from_env() -> Connection:
    """Sim-child end: connect to the host advertised in the environment."""
    port = int(os.environ[LINK_PORT_ENV])
    key = bytes.fromhex(os.environ[LINK_KEY_ENV])
    return Client((_LOCALHOST, port), authkey=key)


def drain(conn: Connection) -> list[Message]:
    """Non-blocking: every message currently queued on *conn*, oldest first.

    A dead peer (closed pipe) yields a final synthetic ``("eof", {})`` so the
    caller can treat disconnection like any other message.
    """
    out: list[Message] = []
    try:
        while conn.poll(0):
            out.append(conn.recv())
    except (EOFError, OSError):
        out.append(("eof", {}))
    return out


def send(conn: Connection, kind: str, payload: dict[str, Any]) -> bool:
    """Send one message; False (never raises) when the peer has gone away."""
    try:
        conn.send((kind, payload))
    except (BrokenPipeError, OSError):
        return False
    return True
