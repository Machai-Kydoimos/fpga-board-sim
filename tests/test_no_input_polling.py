"""All input state must come from the event stream (U44 quality gate).

Stated as a **shape** rule rather than a name list, because pygame-ce ships two
polling APIs upstream pygame never had — ``key.get_just_pressed()`` and
``key.get_just_released()``, new in 2.4.0 — and they are exactly what an
implementer reaches for when adding a hold feature. A gate written against
``get_pressed``/``get_focused`` alone would not have covered them.

Why every one of them is banned here:

* ``get_pressed`` and the ``get_just_*`` pair return a ``ScancodeWrapper`` whose
  ``__getitem__`` re-maps through ``SDL_GetScancodeFromKey``, so ``ks[KSCAN_1]``
  is silently ``False`` forever — the digit tier binds by scancode, so polling
  could never back it up.
* Per pygame-ce's own docs a key reads "just released" *while still held* if it
  was released and re-pressed inside one frame, and multiple presses are not
  distinguished from one — precisely the hold-source state this arc exists to
  get right.
* None of them can see a KEYUP consumed inside a modal's own ``event.get()``
  loop.
* ``get_focused()`` is flavor-dependent: ``False`` under the dummy video driver
  on upstream pygame, ``True`` on pygame-ce.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "fpga_sim"

#: Polling entry points banned on ``pygame.key`` and ``pygame.mouse`` alike.
BANNED = frozenset({"get_pressed", "get_just_pressed", "get_just_released", "get_focused"})

#: Reading the cursor position is not input *state* — it is where to draw the
#: hover tooltip, and it is already used for that.
ALLOWED = frozenset({"get_pos"})


def _python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_there_are_files_to_check():
    """A gate that scans nothing passes vacuously."""
    assert len(_python_files()) > 10


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_no_pygame_input_polling(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        if attr in ALLOWED or attr not in BANNED:
            continue
        owner = node.func.value
        module = getattr(owner, "attr", None) or getattr(owner, "id", None)
        assert module not in ("key", "mouse"), (
            f"{path.name}:{node.lineno} calls pygame.{module}.{attr}() — "
            "all input state must come from the event stream (U44)"
        )


def test_key_repeat_is_never_enabled():
    """A held key must yield exactly one KEYDOWN, which is what a hold needs."""
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "set_repeat", f"{path.name}:{node.lineno}"


def test_no_hardcoded_window_event_integers():
    """pygame-ce renumbered every WINDOW* constant one lower than upstream.

    The literal 32786 means WINDOWFOCUSLOST upstream but WINDOWCLOSE here, so a
    handler written against the old number would fire on window close instead.
    Always compare against the symbol.

    Checked over parsed *constants* rather than raw text: a comment explaining
    this very trap must not trip the gate that enforces it.
    """
    suspicious = range(32764, 32800)
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, int):
                assert node.value not in suspicious, (
                    f"{path.name}:{node.lineno} hardcodes {node.value}, which is in the "
                    "WINDOW*/USEREVENT range — compare against the symbol instead"
                )
