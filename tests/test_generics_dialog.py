"""The [Generics…] editor (U48, decision D-9).

Changing a generic used to mean quitting and relaunching with `--generic`,
which is a poor answer for somebody who has already launched the simulator and
is looking at a board that will not move.  The dialog puts the same lever where
the file was loaded.

What it must never do is edit the design: the values are the *simulator's*, and
the file on disk keeps whatever the real board needs.
"""

import pygame
import pytest

from fpga_sim.generics import design_generics
from fpga_sim.ui.generics_dialog import GenericsDialog

_DESIGN = """
entity running_light is
  generic (
    NUM_SWITCHES : positive := 10;
    NUM_LEDS     : positive := 10;
    COUNTER_BITS : positive := 24;
    CNTR_LEN     : positive := 24;
    INVERTED     : boolean  := false;
    PATTERN      : std_logic_vector(3 downto 0) := "1010"
  );
  port (clk : in bit);
end entity;
"""


@pytest.fixture
def defs():
    return design_generics(_DESIGN, "running_light")


@pytest.fixture
def surface(headless_pygame):
    # The module fixture, not `display.set_mode` -- resizing the global surface
    # here breaks unrelated tests under pytest-randomly.
    return headless_pygame.display.set_mode((1024, 700))


@pytest.fixture
def dialog(surface, defs):
    return GenericsDialog(surface, "running_light.vhd", defs, {})


def _key(dialog, key, unicode=""):
    return dialog._key(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=unicode))


# ── What it offers ───────────────────────────────────────────────────────────


def test_it_starts_from_the_design_own_defaults(dialog):
    assert dialog._values["cntr_len"] == "24"
    assert dialog._values["inverted"] == "false"


def test_an_existing_override_is_what_is_shown(surface, defs):
    d = GenericsDialog(surface, "x.vhd", defs, {"cntr_len": "15"})
    assert d._values["cntr_len"] == "15"


def test_only_editable_rows_can_take_focus(dialog):
    names = dialog._editable_names()
    assert "cntr_len" in names and "counter_bits" in names and "inverted" in names
    assert "num_leds" not in names, "the board sets this one"
    assert "pattern" not in names, "a vector: we would be guessing at the syntax"


# ── What it returns ──────────────────────────────────────────────────────────


def test_an_untouched_dialog_overrides_nothing(dialog):
    assert dialog._overrides() == {}


def test_only_what_differs_from_the_design_is_returned(dialog):
    dialog._values["cntr_len"] = "15"
    dialog._values["counter_bits"] = "24"  # retyping the default is not an override
    assert dialog._overrides() == {"cntr_len": "15"}


def test_apply_returns_the_overrides(dialog):
    dialog._values["cntr_len"] = "15"
    done, answer = dialog._try_apply()
    assert done and answer == {"cntr_len": "15"}


def test_cancel_returns_none_which_means_change_nothing(dialog):
    dialog._values["cntr_len"] = "15"
    dialog._draw()
    assert dialog._cancel_rect is not None
    done, answer = dialog._click(dialog._cancel_rect.center)
    assert done and answer is None


def test_a_bad_value_refuses_to_close_and_says_why(dialog):
    dialog._values["cntr_len"] = "0"  # positive
    done, _ = dialog._try_apply()
    assert not done, "closing on a bad value would fail later, at analysis"
    assert "1 or more" in dialog._error


def test_defaults_puts_everything_back(dialog):
    dialog._values["cntr_len"] = "15"
    dialog._draw()
    assert dialog._reset_rect is not None
    dialog._click(dialog._reset_rect.center)
    assert dialog._values["cntr_len"] == "24"
    assert dialog._overrides() == {}


# ── Typing ───────────────────────────────────────────────────────────────────


def test_typing_edits_the_focused_field(dialog):
    dialog._focus = "cntr_len"
    dialog._values["cntr_len"] = ""
    for ch in "15":
        _key(dialog, ord(ch), ch)
    assert dialog._values["cntr_len"] == "15"


def test_backspace_deletes(dialog):
    dialog._focus = "cntr_len"
    _key(dialog, pygame.K_BACKSPACE)
    assert dialog._values["cntr_len"] == "2"


def test_junk_characters_are_refused(dialog):
    dialog._focus = "cntr_len"
    before = dialog._values["cntr_len"]
    for ch in "@#$ ":
        _key(dialog, ord(ch), ch)
    assert dialog._values["cntr_len"] == before


def test_escape_leaves_the_field_before_it_leaves_the_dialog(dialog):
    dialog._focus = "cntr_len"
    done, _ = _key(dialog, pygame.K_ESCAPE)
    assert not done and dialog._focus is None
    done, answer = _key(dialog, pygame.K_ESCAPE)
    assert done and answer is None


def test_tab_cycles_the_editable_fields(dialog):
    dialog._focus = None
    _key(dialog, pygame.K_TAB)
    first = dialog._focus
    assert first in dialog._editable_names()
    for _ in dialog._editable_names():
        _key(dialog, pygame.K_TAB)
    assert dialog._focus == first, "and wraps"


def test_it_renders(dialog):
    dialog._draw()
    assert dialog._apply_rect is not None
    assert set(dialog._row_rects) == set(dialog._editable_names())
