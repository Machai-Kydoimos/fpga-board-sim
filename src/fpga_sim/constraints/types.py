"""Dialect-agnostic result types shared by every constraint-file parser."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PinEntry:
    """One ``port name -> physical pin/pad`` mapping as written in the source file."""

    port: str
    pin: str


@dataclass(frozen=True)
class ClockConstraint:
    """A clock port's declared frequency, when the dialect states one.

    Only produced when the source text carries an explicit timing statement
    (XDC ``create_clock``, UCF ``TIMESPEC``/``PERIOD``, LPF ``FREQUENCY PORT``);
    most dialects (QSF, PCF, CST, CCF, BoardStore XML) never state one, so
    ``clocks`` is routinely empty.
    """

    port: str
    frequency_hz: float


@dataclass(frozen=True)
class PortTable:
    """Everything one constraint file states about ports: pins plus any clocks."""

    pins: tuple[PinEntry, ...] = field(default_factory=tuple)
    clocks: tuple[ClockConstraint, ...] = field(default_factory=tuple)
