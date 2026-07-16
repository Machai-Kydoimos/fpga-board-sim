"""Tests for the sim_link IPC transport (UI host <-> headless sim child).

Exercises a real loopback host/client pair (no subprocess): the child end is
obtained with ``connect_from_env`` after pointing the env vars at the host's
ephemeral listener, so the round-trips, ``drain`` ordering, EOF synthesis and
``send`` failure handling all run over an actual socket.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from fpga_sim import sim_link
from fpga_sim.sim_link import SimLinkHost, connect_from_env, drain, send

if TYPE_CHECKING:
    from collections.abc import Iterator
    from multiprocessing.connection import Connection


def _collect(conn: Connection, count: int, timeout: float = 2.0) -> list[sim_link.Message]:
    """Drain until *count* messages arrive (or eof / timeout).

    ``drain`` is non-blocking, and a ``send`` on a loopback socket is not always
    visible to the peer's ``poll(0)`` on the very next call — the production host
    simply drains again next frame, so tests do the same instead of racing.
    """
    out: list[sim_link.Message] = []
    deadline = time.monotonic() + timeout
    while len(out) < count and time.monotonic() < deadline:
        out += drain(conn)
        if out and out[-1] == ("eof", {}):
            break
        if len(out) < count:
            time.sleep(0.005)
    return out


@pytest.fixture
def linked(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[SimLinkHost, Connection]]:
    """A connected host<->client pair over a real 127.0.0.1 socket."""
    host = SimLinkHost()
    for key, value in host.env_vars().items():
        monkeypatch.setenv(key, value)
    client = connect_from_env()
    assert host.wait_connected(2.0), "host never accepted the client"
    try:
        yield host, client
    finally:
        client.close()
        host.close()


def test_hello_round_trips(linked: tuple[SimLinkHost, Connection]) -> None:
    host, client = linked
    send(client, "hello", {"pid": 4242})
    assert _collect(host.conn, 1) == [("hello", {"pid": 4242})]


def test_every_child_to_host_kind_round_trips(linked: tuple[SimLinkHost, Connection]) -> None:
    host, client = linked
    messages: list[sim_link.Message] = [
        ("hello", {"pid": 1}),
        (
            "state",
            {
                "led": 3,
                "seg": None,
                "sim_ns": 1000,
                "steps": 2,
                "input_seq": 1,
                "step_ns": 9596,
                "timer_pct": 12.5,
                "at_max": True,
            },
        ),
        ("bye", {"sim_ns": 100, "steps": 3, "wall_s": 1.5}),
    ]
    for kind, payload in messages:
        send(client, kind, payload)
    assert _collect(host.conn, len(messages)) == messages


def test_every_host_to_child_kind_round_trips(linked: tuple[SimLinkHost, Connection]) -> None:
    host, client = linked
    messages: list[sim_link.Message] = [
        ("input", {"sw": 1, "btn": 2, "seq": 5}),
        ("speed", {"factor": 0.5}),
        ("clk", {"half_ns": 20}),
        ("pause", {"on": True}),
        ("stop", {}),
    ]
    for kind, payload in messages:
        send(host.conn, kind, payload)
    assert _collect(client, len(messages)) == messages


def test_drain_preserves_order(linked: tuple[SimLinkHost, Connection]) -> None:
    host, client = linked
    for i in range(5):
        send(client, "state", {"n": i})
    assert [payload["n"] for _kind, payload in _collect(host.conn, 5)] == [0, 1, 2, 3, 4]


def test_drain_empty_when_nothing_queued(linked: tuple[SimLinkHost, Connection]) -> None:
    host, _client = linked
    assert drain(host.conn) == []


def test_drain_delivers_queued_then_synthesizes_eof(
    linked: tuple[SimLinkHost, Connection],
) -> None:
    """A message sent just before the peer closes is still delivered, then eof."""
    host, client = linked
    send(client, "state", {"n": 7})
    client.close()
    # The FIN may lag the buffered payload; poll until eof appears.
    deadline = time.monotonic() + 2.0
    seen: list[sim_link.Message] = []
    while time.monotonic() < deadline:
        seen += drain(host.conn)
        if seen and seen[-1] == ("eof", {}):
            break
        time.sleep(0.01)
    assert ("state", {"n": 7}) in seen
    assert seen[-1] == ("eof", {})


def test_drain_eof_on_a_peer_that_closed_with_nothing_queued(
    linked: tuple[SimLinkHost, Connection],
) -> None:
    host, client = linked
    client.close()
    deadline = time.monotonic() + 2.0
    msgs: list[sim_link.Message] = []
    while time.monotonic() < deadline:
        msgs = drain(host.conn)
        if msgs:
            break
        time.sleep(0.01)
    assert msgs == [("eof", {})]


def test_send_returns_false_on_closed_connection(
    linked: tuple[SimLinkHost, Connection],
) -> None:
    _host, client = linked
    client.close()
    assert send(client, "state", {"n": 1}) is False


def test_wait_connected_is_false_before_any_client() -> None:
    host = SimLinkHost()
    try:
        assert host.wait_connected(0.0) is False
    finally:
        host.close()


def test_env_vars_expose_port_and_key() -> None:
    host = SimLinkHost()
    try:
        env = host.env_vars()
        assert set(env) == {sim_link.LINK_PORT_ENV, sim_link.LINK_KEY_ENV}
        assert env[sim_link.LINK_PORT_ENV].isdigit()
        assert int(env[sim_link.LINK_PORT_ENV]) > 0
        # Key is the 16-byte authkey as hex.
        assert len(bytes.fromhex(env[sim_link.LINK_KEY_ENV])) == 16
    finally:
        host.close()
