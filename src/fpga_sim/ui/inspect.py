"""Inspect mode (U55): a typable address for every place on screen.

A finding in a markdown file has a free address -- ``user_guide.md § Themes`` --
so a comment lands unambiguously.  A finding in the *running app* has none, and
the only way to file one has been to describe the pixels and let the reader grep
for them.  That works for wording, sometimes for behavior, and not at all for
layout, spacing or emphasis.

**F3** paints the missing coordinate system; **F4** copies it.  The address has
two orthogonal halves, and keeping them apart is the whole design:

*The place* is a **region path** -- ``sim.panel.speed.slider``,
``sim.board.led[5]``, ``dlg.settings.debug-view`` -- lowercase, dotted, capped at
three levels plus an index so it stays under ~24 characters.  It is readable at
both ends of a conversation (an opaque ``R23`` would force a lookup for every
reference and mismatch *silently* once the table went stale) and greppable at
this one.

*The state* is a **context stamp**: build, screen, board, design, simulator,
theme, window size.  Baking that into the address would make the address
untypable; leaving it out would make the address unreproducible.

Three things follow from where this has to run.

**Identity is never geometry.**  ``FPGABoard._layout()`` reassigns every widget
rect on resize -- the same reason the hold registries key on widget *index*
rather than rect -- so a path is derived from kind and index, and the rect is
only ever the hit target for this frame.

**The registry is a module global, like ``THEME`` and ``_DEBUG_VIEW``.**  The
point of the design is that :func:`~fpga_sim.ui.widgets.button.draw_button`, a
free function three packages down, can register a button without being handed a
registry; that instruments 17 call sites with one edit.

**Every entry point is a no-op while the overlay is off.**  Registration costs a
single bool read, which is noise beside the two ``draw.rect`` calls and the
``render`` that ``draw_button`` already performs on the same line.  The overlay
must be *free* to leave in, or it would have to be a build flag, and a build
flag is not something a student can be asked to turn on.

The colors here are deliberately **not** THEME roles.  Diagnostic chrome has to
stay legible against a dark PCB, a light panel and a high-contrast scheme alike,
and a palette that a theme could restyle is a palette that a theme could restyle
into invisibility.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

from fpga_sim.ui.clipboard import copy_to_clipboard
from fpga_sim.ui.constants import get_font, render_text
from fpga_sim.version import app_version

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import FrameType

# ── the diagnostic palette (theme-independent by design; see the module docstring)

_INK = (255, 64, 200)  # zone frames, badges, the hovered path
_INK_DIM = (150, 150, 160)  # the context stamp, which is reference rather than answer
_CHIP = (12, 10, 16)  # backing behind every glyph, so text lands on a known ground
_CHIP_ALPHA = 225
_HILITE = (255, 240, 90)  # the one region under the cursor

_ZONE_BORDER = 1
_HILITE_BORDER = 2
_LABEL_PT = 12
_PATH_PT = 17
_STAMP_PT = 12
_PAD = 6
_GAP = 3

#: Keys.  F3/F4 rather than letters because ``BoardSelector`` appends every
#: printable character to its filter text, so no letter is free app-wide.
TOGGLE_KEY = pygame.K_F3
COPY_KEY = pygame.K_F4


@dataclass(frozen=True)
class Region:
    """One addressable place on screen for the current frame.

    *rect* is this frame's hit target and nothing more -- it is reassigned on
    every layout pass.  *path* is the durable half.  *origin* is ``file:line``
    when origin tracing is on and empty otherwise (see :func:`set_trace_origins`).
    """

    path: str
    rect: pygame.Rect
    kind: str  # "zone" | "item" | "widget"
    origin: str = ""


_ENABLED = False
_TRACE_ORIGINS = False
_SCOPE = ""
_REGIONS: list[Region] = []
_CONTEXT: dict[str, str] = {}
#: Set by :func:`draw_overlay`; read by the copy key and by the tests.
_LAST_COPY_OK: bool | None = None


def set_inspect(enabled: bool) -> None:
    """Turn the overlay on or off (the global read at draw time)."""
    global _ENABLED
    _ENABLED = bool(enabled)


def inspect_enabled() -> bool:
    """Whether the inspect overlay is currently painting."""
    return _ENABLED


def set_trace_origins(enabled: bool) -> None:
    """Record ``file:line`` for each registration (``scripts/gen_ui_map.py`` only).

    The product never turns this on.  Walking the stack costs roughly a
    microsecond per region, which is nothing beside a frame but is also nothing
    the overlay needs: a *path* is what a person quotes, and the code behind it
    is a question for a generated map, asked once at build time rather than
    sixty times a second.

    It is a runtime trace rather than a static scan because the two cannot see
    the same thing.  Half the registrations name themselves with an f-string
    (``f"board.led[{i}]"``) and the scope of a shared widget is decided by its
    host (``FPGABoard`` is ``preview`` on one screen and ``sim`` on another), so
    only the running product knows the full path -- and running the real thing
    is the same rule ``--doctor`` follows: a description of what the product
    does can agree with itself while the product disagrees.
    """
    global _TRACE_ORIGINS
    _TRACE_ORIGINS = bool(enabled)


def trace_origins_enabled() -> bool:
    """Whether registrations are recording where they came from."""
    return _TRACE_ORIGINS


#: Modules that only *relay* a registration.  Walking out of them is what makes
#: an origin point at the button's caller rather than at the shared painter
#: every button in the app goes through.
_PLUMBING = ("ui/inspect.py", "ui/widgets/button.py")


def _origin() -> str:
    """Return ``file:line`` of the first frame outside the registration plumbing."""
    frame: FrameType | None = sys._getframe(1)
    while frame is not None:
        name = frame.f_code.co_filename.replace("\\", "/")
        if not any(name.endswith(tail) for tail in _PLUMBING):
            short = name.rsplit("/src/", 1)[-1]
            return f"{short}:{frame.f_lineno}"
        frame = frame.f_back
    return ""


def set_context(**fields: str | None) -> None:
    """Record what the app is working on, for the context stamp.

    Called when a fact *changes* (a board is chosen, a design loads, a run
    starts), never per frame.  A ``None`` value clears its field, which is how
    "no design loaded" is said.
    """
    for key, value in fields.items():
        if value is None:
            _CONTEXT.pop(key, None)
        else:
            _CONTEXT[key] = str(value)


def begin_frame(scope: str) -> None:
    """Start a frame for *scope* (``"sim"``, ``"select"``, ``"dlg.settings"``, …).

    Clears the previous frame's regions unconditionally: a frame that painted
    while the overlay was off registered nothing, and a frame that painted while
    it was on must not leak its rects into a screen that has since resized.
    """
    global _SCOPE
    _SCOPE = scope
    _REGIONS.clear()


def zone(name: str, rect: pygame.Rect) -> None:
    """Register a named area of the current screen (a panel, a list, a footer)."""
    _register(name, rect, "zone")


def item(name: str, rect: pygame.Rect) -> None:
    """Register a piece of chrome (a button, a slider handle) -- drawn with a badge."""
    _register(name, rect, "item")


def widget(name: str, rect: pygame.Rect) -> None:
    """Register a board part: addressable and hoverable, but never badged.

    The distinction is legibility, and it is the whole reason the overlay stays
    readable on a real board.  DE2-115 carries 57 widgets; painting a name on
    each one produces labels wider than the LEDs they name, stacked over the
    board's own ``LED0`` / ``SW3`` captions, which is *less* legible than
    drawing nothing.  These already say what they are -- the address only has to
    say it in the overlay's spelling, which the hover readout does one at a
    time.
    """
    _register(name, rect, "widget")


def _register(name: str, rect: pygame.Rect, kind: str) -> None:
    if not _ENABLED:
        return
    path = f"{_SCOPE}.{name}" if _SCOPE else name
    _REGIONS.append(Region(path, pygame.Rect(rect), kind, _origin() if _TRACE_ORIGINS else ""))


def regions() -> tuple[Region, ...]:
    """Everything registered for the frame just drawn (the tests' way in)."""
    return tuple(_REGIONS)


def scope() -> str:
    """Return the scope :func:`begin_frame` last set."""
    return _SCOPE


def hovered(pos: tuple[int, int]) -> Region | None:
    """Return the smallest registered region containing *pos*, or None.

    Smallest wins so a widget always beats the zone it sits inside; that is the
    only ordering rule, which keeps registration order free.
    """
    best: Region | None = None
    best_area = 0
    for reg in _REGIONS:
        if not reg.rect.collidepoint(pos):
            continue
        area = reg.rect.width * reg.rect.height
        if best is None or area < best_area:
            best, best_area = reg, area
    return best


#: What an unnamed button registers as.  It is deliberately loud rather than
#: absent: ``tests/test_inspect_overlay.py`` renders every screen and fails on
#: any path ending in this, which is what forces the two icon-only buttons
#: (a bare "?" and an empty toggle pill) to pass an explicit ``region``.
UNNAMED = "unnamed"


def slug(label: str) -> str:
    """Turn a button's visible label into a path leaf.

    ``"Back to Boards"`` -> ``"back-to-boards"``.  Punctuation is dropped rather
    than transliterated: a leaf is an identifier, and a label that reduces to
    nothing (an icon-only button) yields :data:`UNNAMED` so the gap shows up on
    screen and in the tests instead of registering a path with a trailing dot.
    """
    out = [c.lower() if c.isalnum() else "-" for c in label.strip()]
    return "-".join(part for part in "".join(out).split("-") if part) or UNNAMED


def context_stamp() -> str:
    """One line describing what the app was showing.

    Assembled at draw time so the window size and theme are the live ones rather
    than whatever they were when the screen was built.
    """
    parts: list[str] = [f"fpga-sim {app_version()}"]
    if _SCOPE:
        parts.append(_SCOPE)
    parts.extend(_CONTEXT[k] for k in ("board", "design", "sim") if k in _CONTEXT)
    # Imported here, not at module scope: ``ui.theme`` imports ``ButtonStyle``
    # from ``ui.widgets.button``, which imports *this* module to register every
    # button it draws.  A top-level import would close that loop.  The cost is a
    # ``sys.modules`` lookup on the frames where the overlay is actually
    # painting, which is the only time this function runs at all.
    from fpga_sim.ui.theme import current_theme_name

    parts.append(current_theme_name())
    surface = pygame.display.get_surface()
    if surface is not None:
        w, h = surface.get_size()
        parts.append(f"{w}x{h}")
    return " · ".join(parts)


def handle_key(ev: pygame.event.Event) -> bool:
    """Handle F3 / F4 from the event stream; return True when *ev* was consumed.

    Called at the top of every screen's KEYDOWN chain.  Consuming the event is
    what keeps the overlay from changing anything else: these two keys are the
    only input it ever takes.
    """
    global _LAST_COPY_OK
    if ev.type != pygame.KEYDOWN:
        return False
    if ev.key == TOGGLE_KEY:
        set_inspect(not _ENABLED)
        return True
    if ev.key == COPY_KEY and _ENABLED:
        target = hovered(pygame.mouse.get_pos())
        path = target.path if target is not None else "(no region)"
        _LAST_COPY_OK = copy_to_clipboard(f"{path} · {context_stamp()}")
        # Also to stdout: a clipboard can be absent (no display server, an SDL
        # build without scrap), and a terminal is the fallback that always works.
        print(f"[fpga-sim] {path} · {context_stamp()}", flush=True)
        return True
    return False


def last_copy_ok() -> bool | None:
    """Whether the last F4 reached the clipboard; None before the first one."""
    return _LAST_COPY_OK


def _chip(surface: pygame.Surface, rect: pygame.Rect) -> None:
    """Paint the translucent backing that makes text legible on any ground."""
    chip = pygame.Surface(rect.size, pygame.SRCALPHA)
    chip.fill((*_CHIP, _CHIP_ALPHA))
    surface.blit(chip, rect.topleft)


def _label_box(surface: pygame.Surface, text: str, topleft: tuple[int, int]) -> pygame.Rect:
    """Return where a label would land, clamped into *surface*."""
    glyphs = render_text(get_font(_LABEL_PT), text, _INK)
    box = pygame.Rect(0, 0, glyphs.get_width() + 2 * _GAP, glyphs.get_height() + 2)
    box.topleft = topleft
    box.clamp_ip(surface.get_rect())
    return box


def _blit_label(
    surface: pygame.Surface, text: str, color: tuple[int, int, int], box: pygame.Rect
) -> None:
    """Draw *text* on a chip filling *box*."""
    _chip(surface, box)
    surface.blit(render_text(get_font(_LABEL_PT), text, color), (box.x + _GAP, box.y + 1))


def _leaf(path: str) -> str:
    """Return a path's last segment, which is what fits beside a widget."""
    return path.rsplit(".", 1)[-1]


def _readout_lines(target: Region | None) -> Iterator[tuple[str, int, tuple[int, int, int]]]:
    """Yield ``(text, point size, color)`` for the readout box, in order."""
    yield (target.path if target is not None else "—", _PATH_PT, _HILITE)
    yield (context_stamp(), _STAMP_PT, _INK_DIM)
    yield ("F3 hide · F4 copy", _STAMP_PT, _INK_DIM)


def _draw_readout(surface: pygame.Surface, target: Region | None, pos: tuple[int, int]) -> None:
    """Draw the fixed readout box, flipping corners so it never hides its subject."""
    rendered = [
        render_text(get_font(pt, bold=pt == _PATH_PT), text, color)
        for text, pt, color in _readout_lines(target)
    ]
    width = max(g.get_width() for g in rendered) + 2 * _PAD
    height = sum(g.get_height() for g in rendered) + 2 * _PAD + _GAP * (len(rendered) - 1)
    box = pygame.Rect(_PAD, _PAD, width, height)
    # The box is chrome the cursor must be able to get behind: when the pointer
    # reaches it, move it to the far corner rather than letting it mask the very
    # region somebody is trying to read.
    if box.collidepoint(pos):
        box.topright = (surface.get_width() - _PAD, _PAD)
    _chip(surface, box)
    pygame.draw.rect(surface, _INK, box, _ZONE_BORDER)
    y = box.y + _PAD
    for glyphs in rendered:
        surface.blit(glyphs, (box.x + _PAD, y))
        y += glyphs.get_height() + _GAP


def draw_overlay(surface: pygame.Surface) -> None:
    """Paint zone frames, widget badges and the readout for the frame just drawn.

    Call immediately before the flip, and *after* any screenshot capture: an
    overlay that reached a still would contaminate every generated board image.
    """
    if not _ENABLED:
        return
    pos = pygame.mouse.get_pos()
    target = hovered(pos)

    # Frames first, so every label lands on top of every frame.
    for reg in _REGIONS:
        if reg.kind == "zone":
            pygame.draw.rect(surface, _INK, reg.rect, _ZONE_BORDER)

    # Then labels, decluttered.  A label that would land on one already placed
    # is dropped rather than stacked: two overlapping names are less readable
    # than one, and nothing is lost, because the hover readout can always name
    # whatever the cursor is on -- including the thing whose badge was dropped.
    placed: list[pygame.Rect] = []

    def _place(text: str, *candidates: tuple[int, int]) -> None:
        """Draw *text* at the first candidate position that is still free."""
        for at in candidates:
            box = _label_box(surface, text, at)
            if any(box.colliderect(other) for other in placed):
                continue
            _blit_label(surface, text, _INK, box)
            placed.append(box)
            return

    for reg in _REGIONS:
        if reg.kind != "zone":
            continue
        # Above the frame when there is room, so the label does not sit over
        # the first thing inside the zone.
        above = reg.rect.y - _LABEL_PT - 4
        _place(reg.path, (reg.rect.x + 2, above), (reg.rect.x + 2, reg.rect.y + 2))
    for reg in _REGIONS:
        if reg.kind == "item":
            # Below the widget, else above it: two buttons side by side put their
            # badges on the same line, and one of the pair can usually step up
            # rather than go unlabeled.
            _place(
                _leaf(reg.path),
                (reg.rect.x, reg.rect.bottom + 1),
                (reg.rect.x, reg.rect.y - _LABEL_PT - 4),
            )

    if target is not None:
        pygame.draw.rect(surface, _HILITE, target.rect.inflate(4, 4), _HILITE_BORDER)
    _draw_readout(surface, target, pos)
