"""Generate ``docs/ui_map.md``: every inspect-mode address, and the code behind it.

Inspect mode (U55) gives a person a *name* for a place on screen.  This turns
that name back into a line of source, which is the half the reader of a bug
report needs.  Keeping the two separable is the point: the name is stable and
quotable, the line number is regenerated, so a report filed against an old
release still resolves against today's tree.

**It renders the real screens.**  Every path in the output came out of the
product's own draw code with the overlay switched on, not out of a scan that
re-derives what that code would do -- the rule ``--doctor`` follows, for the
same reason: a description can stay self-consistent while the thing it
describes moves.  It is also the only approach that *works* here, because half
the registrations name themselves with an f-string and a shared widget's scope
is chosen by whichever screen is hosting it.

Usage::

    uv run python scripts/gen_ui_map.py            # write docs/ui_map.md
    uv run python scripts/gen_ui_map.py --check     # fail if it would change
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

# A dummy video driver, set before pygame is imported, so this runs in CI and
# over ssh.  Mirrors what ``--benchmark`` does in ``__main__``.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pygame  # noqa: E402

from fpga_sim.board_loader import (  # noqa: E402
    discover_boards,
    find_board,
    get_default_boards_path,
)
from fpga_sim.sim_bridge import SimChild  # noqa: E402
from fpga_sim.sim_discovery import SimulatorInfo  # noqa: E402
from fpga_sim.ui import inspect  # noqa: E402
from fpga_sim.ui.board_display import FPGABoard  # noqa: E402
from fpga_sim.ui.board_selector import BoardSelector  # noqa: E402
from fpga_sim.ui.error_dialog import ErrorDialog  # noqa: E402
from fpga_sim.ui.generics_dialog import GenericsDialog  # noqa: E402
from fpga_sim.ui.help_dialog import HelpDialog  # noqa: E402
from fpga_sim.ui.settings_dialog import SettingsDialog  # noqa: E402
from fpga_sim.ui.simulation_screen import SimulationScreen  # noqa: E402
from fpga_sim.ui.vhdl_picker import VHDLFilePicker  # noqa: E402

if TYPE_CHECKING:
    from fpga_sim.ui.inspect import Region

#: Where the generated map lives.
MAP_PATH = REPO_ROOT / "docs" / "ui_map.md"

#: The board every screen is rendered against.  It carries LEDs, switches,
#: buttons *and* a 7-segment display, so every widget family registers at least
#: once; the fleet's other 285 boards differ only in how many of each.
_BOARD = "DE10-Standard"

_SIZE = (1280, 800)

#: Indices collapse in the output: ``led[0]`` and ``led[27]`` are the same line
#: of code and the same kind of question.
_INDEX = re.compile(r"\[\d+\]")


class _StubProc:
    """A process handle that is alive and does nothing, for the sim screen."""

    stderr = None

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


def _fake_sim() -> SimulatorInfo:
    """Return a simulator identity, so the ``SIM:`` toggle and info strip render."""
    return SimulatorInfo(
        engine="ghdl",
        path="/usr/bin/ghdl",
        backend="llvm",
        label="GHDL-LLVM",
        version="5.0.0",
    )


def _collect_screen(draw: Callable[[], object], label: str) -> list[Region]:
    """Run one screen's draw and return what it registered."""
    try:
        draw()
    except Exception as exc:  # pragma: no cover - a screen that will not render
        print(f"  ! {label}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    found = list(inspect.regions())
    print(f"  {label}: {len(found)} regions")
    return found


def collect() -> list[Region]:
    """Render every screen with the overlay on and return every region found."""
    pygame.init()
    screen = pygame.display.set_mode(_SIZE)
    clock = pygame.time.Clock()
    boards = discover_boards(get_default_boards_path())
    board_def = find_board(boards, _BOARD)
    sim = _fake_sim()
    vhdl = REPO_ROOT / "hdl" / "blinky.vhd"

    inspect.set_inspect(True)
    inspect.set_trace_origins(True)
    inspect.set_context(
        board={"name": _BOARD},
        design={"file": vhdl.name, "mode": "generic"},
        simulator={"label": sim.label},
    )

    out: list[Region] = []

    selector = BoardSelector(boards, screen)
    out += _collect_screen(selector._draw, "select")

    preview = FPGABoard(
        board_def=board_def,
        screen=screen,
        width=_SIZE[0],
        height=_SIZE[1],
        sim=sim,
        available_sims=[sim, sim],
        vhdl_path=vhdl,
    )
    preview.generics_hook = lambda: None
    out += _collect_screen(lambda: preview._draw(flip=False), "preview")

    picker = VHDLFilePicker(screen, str(REPO_ROOT / "hdl"))
    out += _collect_screen(picker._draw, "pick")

    child = SimChild(
        proc=cast("Any", _StubProc()),
        link=cast("Any", None),
        wave_cfg=None,
        generics={},
        match=None,
        stderr_tail=deque(),
    )
    sim_screen = SimulationScreen(
        screen,
        clock,
        board_def,
        child,
        speed_factor=1.0,
        match=None,
        vhdl_path=vhdl,
        sim=sim,
        available_sims=[sim, sim],
    )
    sim_screen._connected = True
    sim_screen._show_panel = True

    def _draw_sim() -> None:
        sim_screen.board._draw(flip=False)
        sim_screen.panel.draw()
        sim_screen._draw_overlays()

    out += _collect_screen(_draw_sim, "sim")

    out += _collect_screen(lambda: HelpDialog(screen)._draw(), "dlg.help")
    out += _collect_screen(lambda: SettingsDialog(screen)._draw(), "dlg.settings")
    out += _collect_screen(
        lambda: ErrorDialog(screen, "Title", "Message", example_path=vhdl)._draw(), "dlg.error"
    )
    out += _collect_screen(
        lambda: GenericsDialog(screen, vhdl.name, [], {})._draw(), "dlg.generics"
    )

    inspect.set_inspect(False)
    inspect.set_trace_origins(False)
    return out


def render_markdown(found: list[Region]) -> str:
    """Render the collected regions as the committed map document."""
    #: path -> (kind, origin).  Indices collapse; first origin wins, and a
    #: family registered from one line has exactly one origin anyway.
    rows: dict[str, tuple[str, str]] = {}
    for reg in found:
        path = _INDEX.sub("[i]", reg.path)
        rows.setdefault(path, (reg.kind, reg.origin))

    lines = [
        "# UI map — inspect-mode addresses",
        "",
        # Single spaces after a period: ``rumdl`` normalizes doubles, so a
        # generated file that writes them is rewritten by the formatter on every
        # run and never agrees with its own --check.
        "**Generated — do not edit.** Regenerate with `uv run python scripts/gen_ui_map.py`;",
        "`tests/test_ui_map.py` fails when this file and the product disagree.",
        "",
        "Press **F3** in the app to see these names on screen and **F4** to copy the",
        "one under the cursor. Quote the address in a question or a bug report — it",
        "is stable across releases, which is what makes this table safe to regenerate.",
        "",
        "`[i]` stands for a widget index: `sim.board.led[5]` is LED channel 5, numbered",
        "as `manifest.json`'s LED legend numbers it.",
        "",
        f"{len(rows)} addresses.",
        "",
        "| Address | Kind | Registered at |",
        "| --- | --- | --- |",
    ]
    for path in sorted(rows):
        kind, origin = rows[path]
        lines.append(f"| `{path}` | {kind} | `{origin}` |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Write (or check) ``docs/ui_map.md``; return a process exit code."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if the file would change")
    args = ap.parse_args(argv)

    text = render_markdown(collect())
    if args.check:
        current = MAP_PATH.read_text(encoding="utf-8") if MAP_PATH.exists() else ""
        if current != text:
            print(f"{MAP_PATH.relative_to(REPO_ROOT)} is out of date — regenerate it")
            return 1
        print(f"{MAP_PATH.relative_to(REPO_ROOT)} is up to date")
        return 0
    MAP_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {MAP_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
