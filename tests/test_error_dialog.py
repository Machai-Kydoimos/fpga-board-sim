"""Tests for ErrorDialog: button layout, View-Example behavior, dismiss keys."""

from pathlib import Path
from types import ModuleType

import pygame
import pytest

import fpga_sim.ui.error_dialog as error_dialog_mod
from fpga_sim.ui.error_dialog import ErrorDialog, _wrap_line, _wrap_message
from fpga_sim.ui.results import DialogResult
from fpga_sim.ui.widgets import draw_button

EXAMPLE = Path("/repo/hdl/blinky.vhd")


@pytest.fixture(scope="module")
def screen(headless_pygame):
    return headless_pygame.display.set_mode((1024, 700))


def _dialog(screen: pygame.Surface, example: Path | None = None) -> ErrorDialog:
    return ErrorDialog(screen, "VHDL Error", "boom\nline two", example_path=example)


# ── Button layout ─────────────────────────────────────────────────────────────


class TestButtons:
    def test_two_buttons_without_example(self, screen):
        dlg = _dialog(screen)
        dlg._draw()
        assert dlg._retry_rect is not None
        assert dlg._back_rect is not None
        assert dlg._example_rect is None

    def test_three_buttons_with_example(self, screen):
        dlg = _dialog(screen, EXAMPLE)
        dlg._draw()
        assert dlg._example_rect is not None
        assert dlg._retry_rect is not None
        assert dlg._back_rect is not None
        # Left-to-right order: [View Example] [Try Another File] [Back to Boards]
        assert dlg._example_rect.right <= dlg._retry_rect.left
        assert dlg._retry_rect.right <= dlg._back_rect.left

    def test_buttons_do_not_overlap(self, screen):
        dlg = _dialog(screen, EXAMPLE)
        dlg._draw()
        assert dlg._example_rect is not None and dlg._retry_rect is not None
        assert dlg._back_rect is not None
        assert not dlg._example_rect.colliderect(dlg._retry_rect)
        assert not dlg._retry_rect.colliderect(dlg._back_rect)


# ── Clicks ────────────────────────────────────────────────────────────────────


class TestClicks:
    def test_click_retry(self, screen):
        dlg = _dialog(screen)
        dlg._draw()
        assert dlg._retry_rect is not None
        assert dlg._click(dlg._retry_rect.center) is DialogResult.RETRY

    def test_click_back(self, screen):
        dlg = _dialog(screen)
        dlg._draw()
        assert dlg._back_rect is not None
        assert dlg._click(dlg._back_rect.center) is DialogResult.BACK

    def test_click_outside_buttons_is_noop(self, screen):
        dlg = _dialog(screen)
        dlg._draw()
        assert dlg._click((0, 0)) is None

    def test_click_example_opens_file_and_stays_open(self, screen, monkeypatch):
        opened: list[Path] = []
        monkeypatch.setattr(error_dialog_mod, "open_with_default_app", opened.append)
        dlg = _dialog(screen, EXAMPLE)
        dlg._draw()
        assert dlg._example_rect is not None
        assert dlg._click(dlg._example_rect.center) is None  # dialog not dismissed
        assert opened == [EXAMPLE]


# ── Keyboard ──────────────────────────────────────────────────────────────────


def _post_keys(pygame_: ModuleType, *keys: int) -> None:
    for key in keys:
        pygame_.event.post(pygame_.event.Event(pygame_.KEYDOWN, key=key))


class TestKeys:
    def test_v_opens_example_then_enter_retries(self, screen, headless_pygame, monkeypatch):
        opened: list[Path] = []
        monkeypatch.setattr(error_dialog_mod, "open_with_default_app", opened.append)
        dlg = _dialog(screen, EXAMPLE)
        _post_keys(headless_pygame, pygame.K_v, pygame.K_RETURN)
        assert dlg.run(headless_pygame.time.Clock()) is DialogResult.RETRY
        assert opened == [EXAMPLE]

    def test_v_ignored_without_example(self, screen, headless_pygame, monkeypatch):
        monkeypatch.setattr(
            error_dialog_mod,
            "open_with_default_app",
            lambda p: pytest.fail("opener must not be called without example_path"),
        )
        dlg = _dialog(screen)
        _post_keys(headless_pygame, pygame.K_v, pygame.K_ESCAPE)
        assert dlg.run(headless_pygame.time.Clock()) is DialogResult.BACK


# ── U50/F5: the compiler's caret survives the word wrap ──────────────────────


class _CharFont:
    """A font that measures 10 px per character, so wrap tests state columns.

    The real font is monospace (``get_font`` asks for Consolas, which
    fontconfig substitutes with another monospace face where it is absent), but
    a test that depended on that would be measuring the machine's fonts.
    """

    def size(self, text: str) -> tuple[int, int]:
        return (10 * len(text), 12)


#: GHDL's own three-line shape: message, offending source line, caret column.
GHDL_CARET = (
    'tb.vhd:22:45:error: too many actuals for component instance "uut"\n'
    "    port map (clock, reset, sw, led_r, hex, open, open);\n"
    "                                            ^"
)


def _caret_column(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _record_copies(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture what the dialog puts on the clipboard, without touching one."""
    copied: list[str] = []

    def fake(text: str) -> bool:
        copied.append(text)
        return True

    monkeypatch.setattr(error_dialog_mod, "_copy_to_clipboard", fake)
    return copied


class TestWrapping:
    def test_caret_keeps_its_column_when_the_line_fits(self):
        out = _wrap_message(GHDL_CARET, _CharFont(), 10 * 200)
        source, caret = out[1], out[2]
        assert _caret_column(caret) == 44  # 0-based: GHDL's column 45
        assert source[_caret_column(caret) :].startswith("open")

    def test_indentation_is_preserved_rather_than_stripped(self):
        out = _wrap_message("  indented text\n", _CharFont(), 10 * 200)
        assert out[0] == "  indented text"

    def test_a_wrapped_line_hangs_under_its_own_indent(self):
        raw = "    " + " ".join(["word"] * 8)  # 4-space indent, 39 chars of words
        out = _wrap_line(raw, _CharFont(), 10 * 24)
        assert len(out) > 1
        assert all(line.startswith("    ") for line in out)
        assert all(not line.startswith("     ") for line in out)

    def test_a_token_too_wide_to_fit_is_not_moved_to_column_zero(self):
        raw = "        " + "x" * 40
        assert _wrap_line(raw, _CharFont(), 10 * 12) == [raw]

    def test_wrapping_round_trips_the_original_spacing(self):
        raw = "  signal units   : integer range 0 to 9;"
        assert _wrap_line(raw, _CharFont(), 10 * 500) == [raw]

    def test_caret_follows_the_segment_it_marks_when_the_line_wraps(self):
        out = _wrap_message(GHDL_CARET, _CharFont(), 10 * 48)
        carets = [i for i, line in enumerate(out) if line.strip() == "^"]
        assert len(carets) == 1
        marked = out[carets[0] - 1]
        # The caret still points at 'open', now in the segment that holds it.
        assert marked[_caret_column(out[carets[0]]) :].startswith("open")

    def test_blank_lines_are_kept(self):
        assert _wrap_message("a\n\nb", _CharFont(), 10 * 40) == ["a", "", "b"]

    def test_nvc_gutter_carets_are_left_alone(self):
        """NVC locates its own marker with a line-number gutter; nothing to re-anchor."""
        nvc = (
            "** Error: no visible declaration for UNSIGNED\n"
            "    > /x/bad.vhdl:28\n"
            "    |\n"
            " 28 |   signal counter : unsigned(3 downto 0);\n"
            "    |                    ^^^^^^^^"
        )
        out = _wrap_message(nvc, _CharFont(), 10 * 200)
        assert out[-1] == "    |                    ^^^^^^^^"
        assert out[-2].index("unsigned") == out[-1].index("^")


# ── U50/F5: copy to clipboard ────────────────────────────────────────────────


class TestCopy:
    def test_copy_button_is_first_and_does_not_overlap(self, screen):
        dlg = _dialog(screen, EXAMPLE)
        dlg._draw()
        assert dlg._copy_rect is not None and dlg._example_rect is not None
        assert dlg._copy_rect.right <= dlg._example_rect.left
        assert not dlg._copy_rect.colliderect(dlg._example_rect)

    @pytest.mark.parametrize("size", [(1920, 1080), (1280, 800), (1024, 700), (800, 600)])
    def test_four_buttons_still_fit_the_panel(self, headless_pygame, size):
        """[Copy] made the row four wide, and 1024x700 is the reference size.

        Drawn to an off-screen Surface rather than a resized display: a test
        that called ``set_mode`` would resize the global surface every other
        UI test shares, which ``pytest-randomly`` turns into a failure
        somewhere else.
        """
        surface = headless_pygame.Surface(size)
        dlg = ErrorDialog(surface, "VHDL Error", "boom", example_path=EXAMPLE)
        dlg._draw()
        panel_left = (size[0] - round(size[0] * 2 / 3)) // 2
        assert dlg._copy_rect is not None and dlg._back_rect is not None
        assert dlg._copy_rect.left >= panel_left
        assert dlg._back_rect.right <= panel_left + round(size[0] * 2 / 3)

    def test_click_copies_title_and_message_and_stays_open(self, screen, monkeypatch):
        copied = _record_copies(monkeypatch)
        dlg = _dialog(screen)
        dlg._draw()
        assert dlg._copy_rect is not None
        assert dlg._click(dlg._copy_rect.center) is None
        assert copied == ["VHDL Error\nboom\nline two"]

    def test_c_key_copies(self, screen, headless_pygame, monkeypatch):
        copied = _record_copies(monkeypatch)
        dlg = _dialog(screen)
        _post_keys(headless_pygame, pygame.K_c, pygame.K_ESCAPE)
        assert dlg.run(headless_pygame.time.Clock()) is DialogResult.BACK
        assert len(copied) == 1

    def test_button_confirms_the_copy_then_goes_back_to_its_label(self, screen, monkeypatch):
        monkeypatch.setattr(error_dialog_mod, "_copy_to_clipboard", lambda t: True)
        rendered: list[str] = []

        def spy(surface, rect, label, *args, **kwargs):
            rendered.append(label)
            return draw_button(surface, rect, label, *args, **kwargs)

        monkeypatch.setattr(error_dialog_mod, "draw_button", spy)
        dlg = _dialog(screen)
        dlg.copy()
        dlg._draw()
        assert rendered[0] == "Copied!"
        # Older than the feedback window: the label returns.
        dlg._copied_at = pygame.time.get_ticks() - error_dialog_mod._COPIED_FEEDBACK_MS - 1
        rendered.clear()
        dlg._draw()
        assert rendered[0] == "Copy"

    def test_a_refusing_clipboard_leaves_no_confirmation(self, screen, monkeypatch):
        monkeypatch.setattr(error_dialog_mod, "_copy_to_clipboard", lambda t: False)
        dlg = _dialog(screen)
        assert dlg.copy() is False
        assert dlg._copied_at is None

    def test_clipboard_failure_never_escapes(self, screen, monkeypatch):
        """A dialog explaining a failure must not fail itself (no display, no scrap)."""

        def refuse():
            raise pygame.error("no scrap")

        monkeypatch.setattr(pygame.scrap, "get_init", refuse)
        assert error_dialog_mod._copy_to_clipboard("x") is False
