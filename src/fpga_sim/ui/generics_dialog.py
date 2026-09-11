"""Changing a design's generics without editing the design (U48, decision D-9).

A design whose visible rate comes from the top bits of a clock divider is fine
on the bench and looks dead here.  ``--generic CNTR_LEN=4`` fixes that from the
command line, which is no help at all to somebody who has already launched the
simulator and is looking at a still board -- the advice "restart with a flag" is
a worse answer than it sounds when the student is not sure their design works in
the first place.

So the same lever lives on the preview, where the file was just loaded.  Nothing
here writes to the design: the values are the *simulator's*, they last as long
as the file is loaded, and the file on disk keeps whatever the real board needs.
That is the whole point -- a tool that quietly edited somebody's constant would
make the simulator disagree with their hardware without saying so.

**Apply is explicit.**  Unlike the settings overlay, which writes each row
straight to the session because closing it can lose nothing, a wrong value here
makes a design fail to analyze -- so the dialog validates first and refuses to
close on an error, and [Cancel] really does abandon.
"""

from __future__ import annotations

import pygame

from fpga_sim.generics import GenericDef, validate
from fpga_sim.ui import inspect
from fpga_sim.ui.constants import get_font
from fpga_sim.ui.theme import THEME
from fpga_sim.ui.widgets.button import draw_button

#: Characters a value field will accept.  Deliberately narrow: every editable
#: kind is a number, ``true``/``false`` or a quoted bit, so anything else is a
#: typo the simulator would reject later and more confusingly.
_ALLOWED = set("0123456789_-'truefalseTRUEFALSE")

_MAX_VALUE_LEN = 24

#: ``(the dialog is finished, the answer)``.  A plain return value cannot carry
#: this: ``None`` is a real answer -- the user canceled -- so it cannot also
#: mean "nothing decided yet".
_Outcome = tuple[bool, "dict[str, str] | None"]
_STAY: _Outcome = (False, None)


def _fit(font: pygame.font.Font, text: str, width: int) -> str:
    """Shorten *text* with an ellipsis until it fits *width* pixels."""
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "…")[0] > width:
        text = text[:-1]
    return text + "…"


class GenericsDialog:
    """Modal editor for the picked design's generics, over a dimmed backdrop.

    ``run()`` blocks and returns the new override map on [Apply], or ``None``
    when the user cancels -- which the caller must treat as "change nothing",
    not as "clear everything".
    """

    def __init__(
        self,
        screen: pygame.Surface,
        design_name: str,
        generics: list[GenericDef],
        current: dict[str, str],
    ) -> None:
        """Snapshot *screen* and seed each row from *current* or the design."""
        self.screen = screen
        self._bg = screen.copy()
        self._design_name = design_name
        self._generics = generics
        #: Row text as the user sees it: an override if one is set, else the
        #: design's own default.  Editing is on this, never on the design.
        self._values: dict[str, str] = {
            g.name: current.get(g.name, g.default_text) for g in generics
        }
        self._focus: str | None = None
        self._error: str = ""
        self._row_rects: dict[str, pygame.Rect] = {}
        self._apply_rect: pygame.Rect | None = None
        self._cancel_rect: pygame.Rect | None = None
        self._reset_rect: pygame.Rect | None = None
        self._panel_rect: pygame.Rect | None = None

    # ── the answer ───────────────────────────────────────────────────────────

    def _overrides(self) -> dict[str, str]:
        """Only what actually differs from the design's own default."""
        out: dict[str, str] = {}
        for g in self._generics:
            if not g.editable:
                continue
            value = self._values.get(g.name, "").strip()
            if value and value != g.default_text.strip():
                out[g.name] = value
        return out

    def _validate_all(self) -> str:
        for g in self._generics:
            if not g.editable:
                continue
            value = self._values.get(g.name, "").strip()
            if not value or value == g.default_text.strip():
                continue
            problem = validate(g, value)
            if problem:
                return problem
        return ""

    # ── loop ─────────────────────────────────────────────────────────────────

    def run(self, clock: pygame.time.Clock) -> dict[str, str] | None:
        """Run the blocking loop; return the overrides, or None if canceled."""
        while True:
            for ev in pygame.event.get():
                # Inspect mode (U55) first: it consumes only its own two
                # keys, so nothing this dialog binds can be shadowed.
                if inspect.handle_key(ev):
                    continue
                if ev.type == pygame.QUIT:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                    return None
                if ev.type == pygame.WINDOWRESIZED:
                    self._bg = pygame.Surface((ev.x, ev.y))
                    self._bg.fill(THEME.pcb_bg)
                elif ev.type == pygame.KEYDOWN:
                    done, answer = self._key(ev)
                    if done:
                        return answer
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    done, answer = self._click(ev.pos)
                    if done:
                        return answer
            self._draw()
            clock.tick(30)

    def _key(self, ev: pygame.event.Event) -> _Outcome:
        if ev.key == pygame.K_ESCAPE:
            if self._focus is not None:  # first Esc leaves the field
                self._focus = None
                return _STAY
            return (True, None)
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self._try_apply()
        if ev.key == pygame.K_TAB:
            self._focus_next()
            return _STAY
        if self._focus is None:
            return _STAY
        if ev.key == pygame.K_BACKSPACE:
            self._values[self._focus] = self._values[self._focus][:-1]
            self._error = ""
        elif ev.unicode and ev.unicode in _ALLOWED:
            if len(self._values[self._focus]) < _MAX_VALUE_LEN:
                self._values[self._focus] += ev.unicode
                self._error = ""
        return _STAY

    def _editable_names(self) -> list[str]:
        return [g.name for g in self._generics if g.editable]

    def _focus_next(self) -> None:
        names = self._editable_names()
        if not names:
            return
        if self._focus is None or self._focus not in names:
            self._focus = names[0]
        else:
            self._focus = names[(names.index(self._focus) + 1) % len(names)]

    def _try_apply(self) -> _Outcome:
        self._error = self._validate_all()
        if self._error:
            return _STAY  # a bad value would fail at analysis; say so and wait
        return (True, self._overrides())

    def _click(self, pos: tuple[int, int]) -> _Outcome:
        if self._cancel_rect and self._cancel_rect.collidepoint(pos):
            return (True, None)
        if self._apply_rect and self._apply_rect.collidepoint(pos):
            return self._try_apply()
        if self._reset_rect and self._reset_rect.collidepoint(pos):
            for g in self._generics:
                self._values[g.name] = g.default_text
            self._error = ""
            return _STAY
        for name, rect in self._row_rects.items():
            if rect.collidepoint(pos):
                self._focus = name
                return _STAY
        if self._panel_rect and not self._panel_rect.collidepoint(pos):
            return (True, None)  # click outside == cancel, as elsewhere
        self._focus = None
        return _STAY

    # ── drawing ──────────────────────────────────────────────────────────────

    def _draw(self) -> None:  # noqa: PLR0914 - a dialog is mostly layout
        inspect.begin_frame("dlg.generics")
        self.screen.blit(self._bg, (0, 0))
        dim = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 170))
        self.screen.blit(dim, (0, 0))

        sw, sh = self.screen.get_size()
        scale = min(sw / 1024, sh / 700, 1.4)
        title_f = get_font(max(12, round(16 * scale)), bold=True)
        row_f = get_font(max(10, round(13 * scale)))
        pad = max(10, round(16 * scale))
        row_h = row_f.get_height() + max(6, round(10 * scale))

        rows = self._generics
        body_h = row_h * max(1, len(rows))
        btn_h = row_f.get_height() + max(8, round(12 * scale))
        height = title_f.get_height() + body_h + btn_h + pad * 4
        if self._error:
            height += row_f.get_height() + pad // 2
        width = min(sw - pad * 2, max(560, round(660 * scale)))
        rect = pygame.Rect((sw - width) // 2, (sh - height) // 2, width, height)
        self._panel_rect = rect
        pygame.draw.rect(self.screen, THEME.pcb_bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, THEME.info_green, rect, width=1, border_radius=8)

        y = rect.top + pad
        title = title_f.render(f"Generics — {self._design_name}", True, THEME.sim_info)
        self.screen.blit(title, (rect.left + pad, y))
        y += title_f.get_height() + pad // 2
        pygame.draw.line(
            self.screen, THEME.info_green, (rect.left + pad, y), (rect.right - pad, y), 1
        )
        y += pad // 2

        self._row_rects = {}
        name_x = rect.left + pad
        type_x = name_x + round(190 * scale)
        val_x = type_x + round(110 * scale)
        val_w = round(120 * scale)
        for g in rows:
            fg = THEME.sim_info if g.editable else THEME.sim_hint
            self.screen.blit(row_f.render(g.name.upper(), True, fg), (name_x, y))
            # Types can be long -- `std_logic_vector(3 downto 0)` overruns the
            # value column -- and the type is context, not the thing being
            # edited, so it is the one that gives way.
            self.screen.blit(
                row_f.render(_fit(row_f, g.type_text, val_x - type_x - 8), True, THEME.sim_hint),
                (type_x, y),
            )
            value = self._values.get(g.name, "")
            if g.editable:
                box = pygame.Rect(val_x, y - 3, val_w, row_f.get_height() + 6)
                focused = self._focus == g.name
                pygame.draw.rect(self.screen, THEME.pcb_bg, box, border_radius=3)
                pygame.draw.rect(
                    self.screen,
                    THEME.info_green if focused else THEME.sim_hint,
                    box,
                    width=2 if focused else 1,
                    border_radius=3,
                )
                shown = value + ("_" if focused else "")
                self.screen.blit(row_f.render(shown, True, THEME.sim_info), (box.left + 6, y))
                self._row_rects[g.name] = box
                if value.strip() != g.default_text.strip():
                    note = f"design says {g.default_text}"
                    self.screen.blit(
                        row_f.render(note, True, THEME.sim_hint), (box.right + pad // 2, y)
                    )
            else:
                why = "set by the board" if g.reserved else value or "—"
                self.screen.blit(row_f.render(why, True, THEME.sim_hint), (val_x, y))
            y += row_h

        if self._error:
            y += pad // 4
            self.screen.blit(row_f.render(self._error, True, THEME.title_error), (name_x, y))
            y += row_f.get_height()

        y = rect.bottom - btn_h - pad
        bw = round(110 * scale)
        gap = max(6, round(8 * scale))
        self._apply_rect = pygame.Rect(rect.right - pad - bw, y, bw, btn_h)
        self._cancel_rect = pygame.Rect(self._apply_rect.left - gap - bw, y, bw, btn_h)
        self._reset_rect = pygame.Rect(rect.left + pad, y, bw, btn_h)
        mouse = pygame.mouse.get_pos()
        for r, label, style in (
            (self._reset_rect, "Defaults", THEME.btn_sim_pause),
            (self._cancel_rect, "Cancel", THEME.btn_sim_pause),
            (self._apply_rect, "Apply", THEME.btn_select_board),
        ):
            draw_button(self.screen, r, label, row_f, style, hovered=r.collidepoint(mouse))
        inspect.draw_overlay(self.screen)
        pygame.display.flip()
