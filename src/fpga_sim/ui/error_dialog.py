"""ErrorDialog: modal error overlay with scrollable message and retry/back buttons.

The dialog's whole job is to show a compiler's own words without spoiling
them.  A GHDL diagnostic is three lines -- the message, the offending source
line, and a caret under the offending column -- and the caret is nothing but
leading whitespace, so the wrap must carry indentation through (U50/F5).  NVC
draws the same thing with a gutter and a run of ``^^^^``.
"""

import re
import sys
from pathlib import Path
from typing import Protocol

import pygame

from fpga_sim.platform_open import open_with_default_app
from fpga_sim.ui import inspect
from fpga_sim.ui.clipboard import copy_to_clipboard
from fpga_sim.ui.constants import _ui_scale, get_font
from fpga_sim.ui.results import DialogResult
from fpga_sim.ui.theme import THEME
from fpga_sim.ui.widgets import draw_button

#: "Scroll past the end" -- _draw clamps it to the true maximum, which only it
#: knows (the wrap depends on the font and the window width).
_SCROLL_TO_END = 1 << 30

#: How long the [Copy] button reads "Copied!" before returning to its label.
_COPIED_FEEDBACK_MS = 1500


class _Measurer(Protocol):
    """What wrapping needs of a font: the pixel width of a string.

    Typed as what it uses rather than as ``pygame.font.Font`` so the wrap can
    be tested against a known metric -- a test that measured the machine's own
    fonts would be testing fontconfig.
    """

    def size(self, text: str, /) -> tuple[int, int]: ...


#: GHDL's column marker: a line that is nothing but indentation and carets.
#: NVC draws its own inside a ``|`` gutter, which is self-locating and needs
#: none of the re-anchoring below.
_CARET_LINE = re.compile(r"[ ]*\^+[ ]*")


def _wrap_spans(raw: str, font: _Measurer, max_w: int) -> list[tuple[str, int, int]]:
    """Wrap one line, saying where in the source each rendered segment starts.

    Returns ``(text, src_col, pad)`` per segment: *src_col* is the column in
    *raw* of the segment's first non-indent character, and *pad* is that
    character's index in *text*.  A source column ``c`` therefore renders at
    ``pad + (c - src_col)``, which is what lets a caret be placed under the
    piece of a wrapped line it actually points at.

    The indent is measured once and re-applied to every continuation line, so a
    wrapped source line hangs under itself and an unwrapped caret line keeps
    its column.  Stripping it -- which is what this used to do -- moved every
    caret to column 0, which is worse than not drawing one: it points
    confidently at the wrong character.

    A single token too wide for *max_w* is emitted over-wide rather than moved
    to the left margin; the viewport clips it, and its column stays true.
    """
    stripped = raw.lstrip(" ")
    if not stripped:
        return [(raw, 0, 0)]  # blank, or a line of pure whitespace
    indent = raw[: len(raw) - len(stripped)]
    pad = len(indent)
    spans: list[tuple[str, int, int]] = []
    current = indent
    # "Nothing placed yet" is a flag, not ``current == indent``: a run of
    # spaces splits into empty words, so a break landing on one leaves current
    # back at the indent while a word *has* been placed.  Comparing strings
    # there dropped the separator and shifted every column after it -- and the
    # caret with them.
    empty = True
    start = pad  # source column of current's first content character
    col = pad  # source column of the word about to be placed
    for word in stripped.split(" "):
        candidate = current + word if empty else f"{current} {word}"
        if not empty and font.size(candidate)[0] > max_w:
            spans.append((current, start, pad))
            current = indent + word
            start = col
        else:
            current = candidate
        empty = False
        col += len(word) + 1  # the space that split() consumed
    spans.append((current, start, pad))
    return spans


def _wrap_line(raw: str, font: _Measurer, max_w: int) -> list[str]:
    """Word-wrap one message line to *max_w*, keeping its leading indentation."""
    return [text for text, _, _ in _wrap_spans(raw, font, max_w)]


def _wrap_message(message: str, font: _Measurer, max_w: int) -> list[str]:
    """Wrap *message* for the panel, keeping every caret under what it marks.

    A compiler diagnostic is three lines -- the message, the offending source
    line, and a caret under the offending column.  Preserving the caret's
    indentation is only half the job: once the source line above it wraps, the
    column it counted no longer exists on the row below, and the caret ends up
    pointing at blank space past the end of a continuation.  So a caret line is
    re-anchored -- moved up to follow the segment whose source columns contain
    it, and re-indented into that segment's coordinates.
    """
    wrapped: list[str] = []
    raws = message.split("\n")
    i = 0
    while i < len(raws):
        spans = _wrap_spans(raws[i], font, max_w)
        below = raws[i + 1] if i + 1 < len(raws) else None
        if below is not None and len(spans) > 1 and _CARET_LINE.fullmatch(below):
            caret = below.strip()
            col = len(below) - len(below.lstrip(" "))
            marked = max(
                (k for k, (_, src_col, _) in enumerate(spans) if src_col <= col),
                default=0,
            )
            for k, (text, src_col, pad) in enumerate(spans):
                wrapped.append(text)
                if k == marked:
                    wrapped.append(" " * max(0, pad + col - src_col) + caret)
            i += 2
            continue
        wrapped.extend(text for text, _, _ in spans)
        i += 1
    return wrapped


#: Floor for the button labels when the row will not fit any other way.
_MIN_BUTTON_FONT = 11


def _button_row_metrics(
    labels: list[str], base_size: int, pad: int, gap: int, avail: int
) -> tuple[pygame.font.Font, list[int], int]:
    """Choose a font, padding and gap that fit the button row into *avail*.

    Returns ``(font, widths, gap)``.  [Copy] made the row four buttons wide,
    and the label metrics belong to the machine, not to us: the UI asks for
    Consolas, which Windows has, fontconfig substitutes on Linux, and macOS has
    neither -- there the fallback is wide enough to push four buttons past the
    panel edge at the 1024x700 reference size.  So the fit is computed rather
    than assumed.

    Padding and gaps give way first, because shrinking the labels is the first
    thing a reader notices; the type size only when that is not enough.  If
    even the floor does not fit, the floor is what gets drawn -- a row that
    overflows slightly still beats one whose labels are illegible.
    """
    candidates = [
        (base_size, pad, gap),
        (base_size, max(8, pad // 2), max(6, gap // 2)),
        (base_size, 8, 6),
    ]
    candidates += [(size, 8, 6) for size in range(base_size - 1, _MIN_BUTTON_FONT - 1, -1)]
    font = get_font(base_size, bold=True)
    widths = [font.size(label)[0] + pad for label in labels]
    for size, this_pad, this_gap in candidates:
        font = get_font(size, bold=True)
        widths = [font.size(label)[0] + this_pad for label in labels]
        if sum(widths) + this_gap * (len(labels) - 1) <= avail:
            return font, widths, this_gap
        gap = this_gap
    return font, widths, gap


#: Bound as a module attribute rather than imported under this name: the
#: dialog's tests monkeypatch ``error_dialog._copy_to_clipboard``, and an
#: aliased import is not an export mypy will let them reach.
_copy_to_clipboard = copy_to_clipboard


class ErrorDialog:
    """Modal error dialog drawn over a dimmed snapshot of the current screen.

    Sized to ~1/3 of the main window area (2/3 wide, 1/2 tall).
    run() returns DialogResult.RETRY (Try Another File) or
    DialogResult.BACK (Back to Boards).

    When *example_path* is given, a third [View Example] button (and the V key)
    opens that file with the system's default application — the dialog stays
    open so the user can compare it against the error text.
    """

    def __init__(
        self,
        screen: pygame.Surface,
        title: str,
        message: str,
        example_path: Path | None = None,
    ) -> None:
        """Initialize the dialog with a screen snapshot, title, and message text."""
        self.screen = screen
        self.title = title
        self.message = message
        self.example_path = example_path
        print(f"[error] {title}: {message}", file=sys.stderr, flush=True)
        self._bg = screen.copy()
        self._scroll = 0
        self._retry_rect: pygame.Rect | None = None
        self._back_rect: pygame.Rect | None = None
        self._example_rect: pygame.Rect | None = None
        self._copy_rect: pygame.Rect | None = None
        self._copied_at: int | None = None
        self._line_h = 22
        self._viewport_h = 0
        self._overflowing = False

    def run(self, clock: pygame.time.Clock) -> DialogResult:
        """Run the event loop and return DialogResult.RETRY or DialogResult.BACK."""
        while True:
            for ev in pygame.event.get():
                # Inspect mode (U55) first: it consumes only its own two
                # keys, so nothing this dialog binds can be shadowed.
                if inspect.handle_key(ev):
                    continue
                if ev.type == pygame.QUIT:
                    return DialogResult.BACK
                elif ev.type == pygame.WINDOWRESIZED:
                    # Rebuild background at new size so the dim overlay fills correctly
                    self._bg = pygame.Surface((ev.x, ev.y))
                    self._bg.fill(THEME.sel_bg)
                    self._scroll = 0
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return DialogResult.BACK
                    elif ev.key == pygame.K_RETURN:
                        return DialogResult.RETRY
                    elif ev.key == pygame.K_v and self.example_path is not None:
                        open_with_default_app(self.example_path)
                    elif ev.key == pygame.K_c:
                        self.copy()
                    else:
                        self._scroll_key(ev.key)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        result = self._click(ev.pos)
                        if result is not None:
                            return result
                    elif ev.button == 4:
                        self._scroll = max(0, self._scroll - 60)
                    elif ev.button == 5:
                        self._scroll += 60

            self._draw()
            clock.tick(30)

    def _footer_hint(self) -> str:
        """Build the keys line under the panel, naming only what this dialog can do.

        Scrolling is offered only when there is something below the fold: a key
        that does nothing is a question the reader has to answer before
        ignoring it.
        """
        text = "C: Copy    Enter: Try Another File    Esc: Back to Boards"
        if self.example_path is not None:
            text = f"V: View Example    {text}"
        if self._overflowing:
            text = f"\u2191\u2193 PgUp/PgDn: Scroll    {text}"
        return text

    def _scroll_key(self, key: int) -> None:
        """Move the message under the keys a reader reaches for.

        The wheel was the only way to see the rest of a message, which leaves
        out anyone on a trackpad-less keyboard -- and the hints this dialog now
        carries are several lines longer than the text it was built for.
        """
        page = max(self._line_h, self._viewport_h - self._line_h)
        if key in (pygame.K_DOWN, pygame.K_KP2):
            self._scroll += self._line_h
        elif key in (pygame.K_UP, pygame.K_KP8):
            self._scroll = max(0, self._scroll - self._line_h)
        elif key == pygame.K_PAGEDOWN:
            self._scroll += page
        elif key == pygame.K_PAGEUP:
            self._scroll = max(0, self._scroll - page)
        elif key == pygame.K_HOME:
            self._scroll = 0
        elif key == pygame.K_END:
            self._scroll = _SCROLL_TO_END  # clamped to the real end by _draw

    def _click(self, pos: tuple[int, int]) -> DialogResult | None:
        if self._retry_rect and self._retry_rect.collidepoint(pos):
            return DialogResult.RETRY
        if self._back_rect and self._back_rect.collidepoint(pos):
            return DialogResult.BACK
        if self._example_rect and self._example_rect.collidepoint(pos):
            # Opens externally; the dialog stays up so the user can compare.
            assert self.example_path is not None
            open_with_default_app(self.example_path)
        if self._copy_rect and self._copy_rect.collidepoint(pos):
            self.copy()
        return None

    def copy(self) -> bool:
        """Put the title and the whole message on the clipboard, hints included.

        The whole thing, unwrapped: what a student does next with a compiler
        error is paste it somewhere -- a search engine, a message to whoever
        is teaching them -- and the part they would have to scroll to reach is
        exactly the part worth sending.
        """
        ok = _copy_to_clipboard(f"{self.title}\n{self.message}")
        self._copied_at = pygame.time.get_ticks() if ok else None
        return ok

    def _draw(self) -> None:
        inspect.begin_frame("dlg.error")
        sw, sh = self.screen.get_size()
        s = _ui_scale(sw, sh)

        # Dimmed background
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(self._bg, (0, 0))
        self.screen.blit(overlay, (0, 0))

        # Scale everything to the window — panel is ~2/3 wide, content area ~1/3 tall
        pad = max(20, round(28 * s))
        panel_w = round(sw * 2 / 3)
        btn_h = max(38, round(50 * s))
        btn_gap = max(12, round(16 * s))
        btns_h = btn_h + btn_gap * 2

        title_f = get_font(max(20, round(26 * s)), bold=True)
        body_f = get_font(max(16, round(20 * s)))
        line_h = body_f.get_linesize() + 2

        # Word-wrap message lines to fit panel width, indentation preserved
        max_text_w = panel_w - pad * 2
        wrapped = _wrap_message(self.message, body_f, max_text_w)

        # The body gets the room the window actually has, not a fixed third of
        # it, and always a whole number of lines: a viewport that ended
        # mid-glyph drew a half-row of pixels at the bottom edge, which reads
        # as text running off the panel rather than as text you can scroll.
        body_h = len(wrapped) * line_h
        chrome = pad + title_f.get_linesize() + pad + btns_h + pad
        avail = sh - chrome - max(40, round(72 * s))  # margins + the footer hint
        viewport_h = min(body_h, max(3 * line_h, avail))
        viewport_h -= viewport_h % line_h
        panel_h = pad + title_f.get_linesize() + pad + viewport_h + btns_h + pad
        # Remembered for the keyboard: run() scrolls, _draw() is what knows the
        # line height and how much of the message is off-screen.
        self._line_h = line_h
        self._viewport_h = viewport_h
        self._overflowing = body_h > viewport_h

        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2
        inspect.zone("panel", pygame.Rect(px, py, panel_w, panel_h))

        # Panel background
        panel_rect = pygame.Rect(px, py, panel_w, panel_h)
        pygame.draw.rect(self.screen, THEME.panel_bg, panel_rect, border_radius=10)
        pygame.draw.rect(self.screen, THEME.panel_border_error, panel_rect, 2, border_radius=10)

        # Title
        t = title_f.render(self.title, True, THEME.title_error)
        self.screen.blit(t, (px + pad, py + pad))

        # Scrollable body text
        body_top = py + pad + title_f.get_linesize() + pad
        max_scroll = max(0, body_h - viewport_h)
        self._scroll = min(self._scroll, max_scroll)

        clip = pygame.Rect(px + pad, body_top, max_text_w, viewport_h)
        self.screen.set_clip(clip)
        for i, line in enumerate(wrapped):
            ly = body_top + i * line_h - self._scroll
            if ly + line_h < body_top or ly > body_top + viewport_h:
                continue
            surf = body_f.render(line, True, THEME.body_text)
            self.screen.blit(surf, (px + pad, ly))
        self.screen.set_clip(None)

        # Scroll indicator
        if body_h > viewport_h:
            sb_x = px + panel_w - 8
            thumb_h = max(20, viewport_h * viewport_h // body_h)
            thumb_y = body_top + (self._scroll * (viewport_h - thumb_h) // max(1, max_scroll))
            pygame.draw.rect(
                self.screen,
                THEME.scroll_track,
                pygame.Rect(sb_x, body_top, 5, viewport_h),
                border_radius=2,
            )
            pygame.draw.rect(
                self.screen,
                THEME.scroll_thumb,
                pygame.Rect(sb_x, thumb_y, 5, thumb_h),
                border_radius=2,
            )

        # Buttons: [Copy] [View Example] (optional) [Try Another File] [Back to Boards]
        btn_y = py + panel_h - btns_h + btn_gap
        copied = (
            self._copied_at is not None
            and pygame.time.get_ticks() - self._copied_at < _COPIED_FEEDBACK_MS
        )
        buttons = [("Copied!" if copied else "Copy", THEME.btn_select_board, "_copy_rect")]
        if self.example_path is not None:
            buttons.append(("View Example", THEME.btn_load_vhdl, "_example_rect"))
        buttons += [
            ("Try Another File", THEME.btn_error_retry, "_retry_rect"),
            ("Back to Boards", THEME.btn_error_back, "_back_rect"),
        ]
        btn_f, widths, gap = _button_row_metrics(
            [label for label, _, _ in buttons],
            max(16, round(20 * s)),
            pad,
            btn_gap,
            panel_w - btn_gap,
        )
        total_btn_w = sum(widths) + gap * (len(buttons) - 1)
        bx = px + (panel_w - total_btn_w) // 2

        mouse = pygame.mouse.get_pos()
        self._example_rect = None
        for (label, style, attr), w in zip(buttons, widths, strict=True):
            rect = pygame.Rect(bx, btn_y, w, btn_h)
            setattr(self, attr, rect)
            draw_button(
                self.screen,
                rect,
                label,
                btn_f,
                style,
                hovered=rect.collidepoint(mouse),
            )
            bx += w + gap

        # Keyboard shortcut hint below the panel
        hint_f = get_font(max(12, round(14 * s)))
        hint = hint_f.render(self._footer_hint(), True, THEME.footer_hint)
        self.screen.blit(hint, hint.get_rect(centerx=px + panel_w // 2, top=py + panel_h + 8))

        inspect.draw_overlay(self.screen)
        pygame.display.flip()
