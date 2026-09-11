"""Tests for ErrorDialog: button layout, View-Example behavior, dismiss keys."""

import random
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pygame
import pytest

import fpga_sim.ui.error_dialog as error_dialog_mod
from fpga_sim.ui.constants import get_font
from fpga_sim.ui.error_dialog import ErrorDialog, _wrap_line, _wrap_message, _wrap_spans
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


class _FixedMetricFont:
    """A real font that reports a fixed width per character.

    Absolute, not a multiple of the machine's own metrics: a proxy defined as
    "1.5x whatever this computer has" compounds with the platform and asks a
    macOS runner (already ~17% wider than Linux) for a fit no legible type size
    can deliver.  Rendering is delegated unchanged -- only the measurements the
    layout reads are synthetic, which is all the layout has to survive.
    """

    #: px per character at each point of type size.  0.7 puts a 20 px bold
    #: label within a pixel or two of what macOS actually measures, which is
    #: the environment that found the defect this guards.
    ADVANCE = 0.7

    def __init__(self, real: pygame.font.Font, size: int) -> None:
        self._real = real
        self._advance = max(1, round(self.ADVANCE * size))

    def size(self, text: str) -> tuple[int, int]:
        return self._advance * len(text), self._real.get_height()

    def __getattr__(self, name: str) -> object:  # render, get_linesize, ...
        return getattr(self._real, name)


def _use_fixed_metric_font(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every font the dialog asks for measure a fixed width per character."""

    def fixed(size: int, bold: bool = False) -> _FixedMetricFont:
        return _FixedMetricFont(get_font(size, bold=bold), size)

    monkeypatch.setattr(error_dialog_mod, "get_font", fixed)


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
    def test_four_buttons_still_fit_the_panel(self, screen, headless_pygame, size):
        """[Copy] made the row four wide, and 1024x700 is the reference size.

        Drawn to an off-screen Surface rather than a resized display: a test
        that called ``set_mode`` would resize the global surface every other UI
        test shares, which ``pytest-randomly`` turns into a failure somewhere
        else.  It still asks for ``screen``, because ``_draw`` ends in
        ``display.flip()`` and a display mode has to exist -- relying on
        another test to have set one is the same order dependency by a
        different route.

        This measures the machine's own font.  The width the *layout* must
        survive is tested against a synthetic metric in
        :class:`TestButtonRowFits`, because the machine's is not the widest.
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
        """A dialog explaining a failure must not fail itself (no display, no scrap).

        Patches ``put_text`` because that is the call the shared helper makes:
        ``scrap.init()``/``get_init()`` were deprecated in pygame-ce 2.2 and
        warned on every copy, so ``ui.clipboard`` dropped them.
        """

        def refuse(_text):
            raise pygame.error("no scrap")

        monkeypatch.setattr(pygame.scrap, "put_text", refuse)
        assert error_dialog_mod._copy_to_clipboard("x") is False


# ── U50/F5: the row is fitted, not assumed ───────────────────────────────────


class TestButtonRowFits:
    """`_button_row_metrics` against a synthetic width, so every machine agrees.

    The four-button row fitted on Linux and overflowed the panel on macOS,
    whose fallback for the UI's Consolas is ~17% wider — at the **1024x700
    reference size**, which is the window the app opens at.  Padding and gaps
    alone could not absorb it, so the type size has to give way too.
    """

    LABELS = ["Copy", "View Example", "Try Another File", "Back to Boards"]
    #: 1024x700: panel 683 wide, the fitter is handed panel_w - gap.
    REFERENCE = dict(base_size=20, pad=28, gap=16, avail=667)

    @pytest.fixture(autouse=True)
    def _font_module_is_up(self, headless_pygame):
        """`_button_row_metrics` calls `get_font`, which needs `font.init()`.

        Nothing else in this class touches pygame, so without this the tests
        pass only when some *other* test happened to initialize it first --
        which is a coin flip under `pytest-randomly`, and was green for two
        weeks before a seed put this class first and CI failed with
        `pygame.error: font not initialized`.  Requesting the fixture is the
        same fix `TestScrolling` needed for `display.set_mode`.
        """

    def _fit(self, monkeypatch, **kwargs):
        _use_fixed_metric_font(monkeypatch)
        args = {**self.REFERENCE, **kwargs}
        font, widths, gap = error_dialog_mod._button_row_metrics(
            self.LABELS, args["base_size"], args["pad"], args["gap"], args["avail"]
        )
        return font, sum(widths) + gap * (len(self.LABELS) - 1)

    def test_a_wide_font_still_fits_at_the_reference_size(self, monkeypatch):
        """The macOS regression, stated in a way every platform can check."""
        _, total = self._fit(monkeypatch)
        assert total <= self.REFERENCE["avail"]

    def test_a_comfortable_row_keeps_the_full_type_size(self, monkeypatch):
        """Nothing is shrunk gratuitously: a wide window looks as it always did."""
        font, total = self._fit(monkeypatch, avail=2000)
        assert font._advance == round(_FixedMetricFont.ADVANCE * 20)
        assert total <= 2000

    def test_padding_gives_way_before_the_labels(self, monkeypatch):
        """A row that only just overflows is fixed by squeezing, not by shrinking."""
        nominal_font, nominal = self._fit(monkeypatch, avail=10_000)
        font, total = self._fit(monkeypatch, avail=nominal - 4)
        assert total <= nominal - 4
        assert font._advance == nominal_font._advance  # same type size

    def test_an_impossible_row_falls_back_to_the_floor(self, monkeypatch):
        """Below the legibility floor it overflows rather than becoming specks."""
        font, total = self._fit(monkeypatch, avail=10)
        assert font._advance == round(_FixedMetricFont.ADVANCE * error_dialog_mod._MIN_BUTTON_FONT)
        assert total > 10  # honest about not fitting, rather than illegible


# ── U50/F5: the wrap holds up as a property, not just on the cases I picked ──


def _random_lines(seed: int, count: int = 400) -> Iterator[tuple[str, int]]:
    """Diagnostic-shaped lines: an indent, then words of assorted lengths."""
    rng = random.Random(seed)
    for _ in range(count):
        indent = " " * rng.choice([0, 0, 1, 2, 4, 8, 17, 40])
        words = [
            "".join(rng.choice("abcdefgh(),;=>_^") for _ in range(rng.randint(1, 18)))
            for _ in range(rng.randint(1, 14))
        ]
        # Runs of spaces occur in real source; they must survive the round trip.
        text = " ".join(words)
        if rng.random() < 0.3:
            text = text.replace(" ", "   ", 1)
        yield indent + text, rng.choice([40, 80, 140, 300, 900])


class TestWrapProperties:
    """The caret rests on `_wrap_spans`' claim that a segment maps back to a
    source column.  These check that claim over a few hundred generated lines
    rather than over the four diagnostics that happened to get typed out."""

    FONT = _CharFont()

    def test_a_segment_maps_back_to_the_source_it_came_from(self):
        """`text[pad:] is raw[src_col:...]` — the mapping the caret is placed by."""
        for raw, width in _random_lines(seed=20260907):
            for text, src_col, pad in _wrap_spans(raw, self.FONT, width):
                assert text[pad:] == raw[src_col : src_col + len(text) - pad], raw

    def test_no_character_is_lost_or_invented(self):
        for raw, width in _random_lines(seed=1):
            spans = _wrap_spans(raw, self.FONT, width)
            rebuilt = spans[0][0]
            for text, _, pad in spans[1:]:
                rebuilt += " " + text[pad:]  # the space that split() consumed
            assert rebuilt == raw, raw

    def test_every_segment_keeps_the_original_indent(self):
        for raw, width in _random_lines(seed=2):
            indent = raw[: len(raw) - len(raw.lstrip(" "))]
            for text, _, _ in _wrap_spans(raw, self.FONT, width):
                assert text.startswith(indent)
        # A continuation may begin with *further* spaces -- a break can land
        # inside a run of them, and those belong to the source.  That they are
        # the source's own is what test_a_segment_maps_back_to_the_source
        # checks; it is not a defect in the indent.

    def test_a_segment_is_over_wide_only_when_one_token_is(self):
        for raw, width in _random_lines(seed=3):
            for text, _, pad in _wrap_spans(raw, self.FONT, width):
                if self.FONT.size(text)[0] > width:
                    assert " " not in text[pad:], f"{text!r} could have been broken"

    def test_wrapping_is_idempotent_on_a_line_that_already_fits(self):
        for raw, _ in _random_lines(seed=4):
            once = _wrap_line(raw, self.FONT, 10_000)
            assert once == [raw]


# ── U50: the message is readable without a mouse, and never half-drawn ───────

#: Longer than any panel: 60 diagnostic-shaped lines.
LONG = "\n".join(
    f"design.vhd:{i}:12:error: a fairly long sentence about line {i}" for i in range(60)
)


class TestScrolling:
    """Rick, reading the stills: "there is more text than can fit ... it runs on
    off the bottom".  The viewport was a fixed third of the window and never a
    whole number of lines, so the bottom row was always drawn half-clipped --
    and the wheel was the only way to reach the rest."""

    SIZES = [(1920, 1080), (1280, 800), (1024, 700), (900, 620), (800, 600), (640, 480)]

    @pytest.mark.parametrize("size", SIZES)
    def test_the_viewport_is_a_whole_number_of_lines(self, screen, headless_pygame, size):
        dlg = ErrorDialog(headless_pygame.Surface(size), "VHDL Error", LONG)
        dlg._draw()
        assert dlg._viewport_h % dlg._line_h == 0

    @pytest.mark.parametrize("size", SIZES)
    def test_the_panel_stays_inside_the_window(self, screen, headless_pygame, size):
        """Giving the body more room must not push the buttons off the bottom."""
        dlg = ErrorDialog(headless_pygame.Surface(size), "VHDL Error", LONG)
        dlg._draw()
        assert dlg._back_rect is not None
        assert dlg._back_rect.bottom < size[1]

    def test_a_message_that_fits_is_shown_whole(self, screen, headless_pygame):
        """The hinted errors this PR produces are ~13 lines; they should not
        need scrolling at any window size a student is likely to use."""
        hinted = (
            'tb.vhd:22:45:error: too many actuals for component instance "uut"\n'
            "    port map (clock, reset, sw, led_r, hex, open, open);\n"
            "                                            ^\n\n"
            "Hint: The port map lists more actuals than the entity has ports.\n"
            "A positional port map binds by position, so it silently changes meaning "
            "whenever the entity's port list does. Name the ports instead:\n"
            "  port map (clk => clk, rst => rst, sw => sw);"
        )
        for size in [(1920, 1080), (1280, 800), (1024, 700), (900, 620), (800, 600)]:
            dlg = ErrorDialog(headless_pygame.Surface(size), "VHDL Error", hinted)
            dlg._draw()
            assert not dlg._overflowing, f"needs scrolling at {size}"

    def test_the_footer_offers_scrolling_only_when_there_is_more(self, screen, headless_pygame):
        small = ErrorDialog(headless_pygame.Surface((1280, 800)), "VHDL Error", "boom")
        small._draw()
        assert "Scroll" not in small._footer_hint()
        big = ErrorDialog(headless_pygame.Surface((640, 480)), "VHDL Error", LONG)
        big._draw()
        assert "Scroll" in big._footer_hint()

    def test_the_keyboard_reaches_the_rest_of_the_message(self, screen, headless_pygame):
        dlg = ErrorDialog(headless_pygame.Surface((800, 600)), "VHDL Error", LONG)
        dlg._draw()
        assert dlg._overflowing
        dlg._scroll_key(pygame.K_DOWN)
        assert dlg._scroll == dlg._line_h
        dlg._scroll_key(pygame.K_UP)
        assert dlg._scroll == 0
        dlg._scroll_key(pygame.K_UP)
        assert dlg._scroll == 0  # never above the first line
        dlg._scroll_key(pygame.K_PAGEDOWN)
        assert dlg._scroll > dlg._line_h
        dlg._scroll_key(pygame.K_END)
        dlg._draw()  # _draw owns the clamp: only it knows how long the wrap is
        at_end = dlg._scroll
        assert 0 < at_end < error_dialog_mod._SCROLL_TO_END
        dlg._scroll_key(pygame.K_DOWN)
        dlg._draw()
        assert dlg._scroll == at_end  # the end is the end
        dlg._scroll_key(pygame.K_HOME)
        assert dlg._scroll == 0

    def test_scrolling_keys_do_not_dismiss_the_dialog(self, screen, headless_pygame):
        """They fall through the same KEYDOWN branch as Enter and Esc."""
        dlg = ErrorDialog(headless_pygame.Surface((800, 600)), "VHDL Error", LONG)
        _post_keys(headless_pygame, pygame.K_DOWN, pygame.K_PAGEDOWN, pygame.K_END, pygame.K_ESCAPE)
        assert dlg.run(headless_pygame.time.Clock()) is DialogResult.BACK
        assert dlg._scroll > 0
