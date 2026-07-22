"""Low-level UI components: FPGAChip, LED, Switch, Button.

These are the building blocks placed on the board canvas by FPGABoard.
"""

import abc
from collections.abc import Callable, Sequence

import pygame

from fpga_sim.board_loader import ComponentInfo
from fpga_sim.ui.constants import GRAY, WHITE, lerp_rgb
from fpga_sim.ui.constants import get_font as _get_font
from fpga_sim.ui.theme import THEME

# ── Component classes ────────────────────────────────────────────────


class FPGAChip:
    """Visual representation of the FPGA IC package on the board."""

    # Palette roles are read from THEME at draw time (never captured here) so a
    # set_theme() swap restyles the chip; geometry and the neutral border stay.
    _BORDER_COLOR = GRAY
    _PIN_LENGTH = 5

    def __init__(
        self, vendor: str = "", device: str = "", package: str = "", clock_hz: float = 0.0
    ) -> None:
        """Initialize the chip with optional vendor, device, package, and clock metadata."""
        self.vendor = vendor
        self.device = device
        self.package = package
        self.clock_hz = clock_hz
        self.rect = pygame.Rect(0, 0, 0, 0)

    @staticmethod
    def _fmt_clock(hz: float) -> str:
        if hz >= 1e6:
            mhz = hz / 1e6
            return f"{mhz:g} MHz"
        if hz >= 1e3:
            return f"{hz / 1e3:g} kHz"
        return f"{hz:g} Hz"

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Draw the FPGA chip package with vendor color, pin marks, and text labels."""
        if self.rect.width < 20:
            return
        r = self.rect
        color = THEME.vendor_colors.get(self.vendor, THEME.chip_default)

        pygame.draw.rect(surface, color, r, border_radius=6)
        pygame.draw.rect(surface, self._BORDER_COLOR, r, 2, border_radius=6)
        self._draw_pin_marks(surface, r)

        cx, cy = r.centerx, r.centery
        line_h = font.get_linesize()
        lines = [
            (
                self.vendor,
                WHITE,
            ),
            (
                self.device.upper(),
                THEME.chip_device,
            ),
            (
                self.package.upper(),
                THEME.chip_package,
            ),
        ]
        if self.clock_hz:
            lines.append((self._fmt_clock(self.clock_hz), THEME.chip_clock))
        active = [(t, c) for t, c in lines if t]
        offset = -(len(active) - 1) / 2 * line_h
        for text, color in active:
            s = font.render(text, True, color)
            surface.blit(s, s.get_rect(centerx=cx, centery=cy + offset))
            offset += line_h

    def _draw_pin_marks(self, surface: pygame.Surface, r: pygame.Rect) -> None:
        color = THEME.chip_pin
        length = self._PIN_LENGTH
        h_count = max(4, min(20, r.width // 14))
        v_count = max(4, min(14, r.height // 14))

        for i in range(h_count):
            x = r.left + (i + 1) * r.width // (h_count + 1)
            pygame.draw.line(surface, color, (x, r.top), (x, r.top - length))
            pygame.draw.line(surface, color, (x, r.bottom), (x, r.bottom + length))

        for i in range(v_count):
            y = r.top + (i + 1) * r.height // (v_count + 1)
            pygame.draw.line(surface, color, (r.left, y), (r.left - length, y))
            pygame.draw.line(surface, color, (r.right, y), (r.right + length, y))


class UIComponent(abc.ABC):
    """Abstract base for the indexed, info-carrying board widgets.

    ``LED``, ``Switch``, and ``Button`` share an identical ``(index, info)``
    construction signature, the same ``label`` derivation, and the
    ``index`` / ``info`` / ``rect`` attributes; subclasses add their own
    interactive state (``state`` / ``pressed`` / ``callback``) and implement
    :meth:`draw`.  ``FPGAChip`` and ``SevenSeg`` are intentionally *not*
    subclasses — neither is ``(index, info)``-based.
    """

    #: Fallback label prefix, e.g. ``"LED"``; used when no ComponentInfo is set.
    _LABEL_PREFIX: str = ""

    def __init__(self, index: int, info: ComponentInfo | None = None) -> None:
        """Initialize with the board index and optional component metadata."""
        self.index = index
        self.info = info
        self.rect = pygame.Rect(0, 0, 0, 0)

    @property
    def label(self) -> str:
        """Human-readable label from ComponentInfo, else ``<PREFIX><index>``."""
        return self.info.display_name if self.info else f"{self._LABEL_PREFIX}{self.index}"

    @property
    def tooltip_extra(self) -> list[tuple[str, str]]:
        """Extra ``(prefix, value)`` hover rows beyond the shared pin metadata.

        Empty by default; a subclass with live state worth surfacing (an LED's
        measured duty cycle) overrides it.
        """
        return []

    @abc.abstractmethod
    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Render the component onto *surface*, using *font* for its label."""


#: Perceptual gamma for duty -> brightness.  Luminance is linear in duty cycle,
#: but perception is not: a 10%-duty LED looks clearly lit on real hardware,
#: where a linear ramp would render it as nearly black.
GAMMA: float = 2.2


def _perceptual(level: float) -> float:
    """Map a linear duty cycle in [0, 1] to a perceptual brightness fraction."""
    return float(max(0.0, min(1.0, level)) ** (1.0 / GAMMA))


# LED emission colors (U36). Vivid "lit" RGBs for the schema's named colors; an
# unknown/absent color falls back to THEME.led_on at draw time (never captured
# here -- the U6 theme trap). #RRGGBB values from board data are parsed directly.
_LED_COLOR_RGB: dict[str, tuple[int, int, int]] = {
    "red": (255, 60, 55),
    "green": (60, 225, 95),
    "blue": (70, 130, 255),
    "yellow": (250, 225, 70),
    "orange": (255, 150, 45),
    "amber": (255, 190, 50),
    "white": (245, 245, 255),
}


def resolve_led_color(color: str) -> tuple[int, int, int] | None:
    """Map a board ``color`` (a named color or ``#RRGGBB``) to an RGB triple.

    Returns ``None`` when the color is empty or unrecognized, so the caller can
    fall back to the theme's default LED color.
    """
    if not color:
        return None
    if color.startswith("#") and len(color) == 7:
        try:
            return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
        except ValueError:
            return None
    return _LED_COLOR_RGB.get(color)


class LED(UIComponent):
    """A read-only indicator controlled via FPGABoard.set_led()/set_led_level().

    Carries a *continuous* :attr:`level` (the measured duty cycle, U9) rather
    than a bool, so a PWM-driven LED renders at its actual brightness.  The
    ``state`` bool remains as a view over it, so binary callers are unaffected.
    """

    _LABEL_PREFIX = "LED"

    def __init__(self, index: int, info: ComponentInfo | None = None) -> None:
        """Initialize the LED with its board index and optional component metadata."""
        super().__init__(index, info)
        self.level: float = 0.0
        # Resolved emission color (U36); None -> theme default at draw time.
        self._on_color: tuple[int, int, int] | None = resolve_led_color(info.color if info else "")

    @property
    def state(self) -> bool:
        """Binary view of :attr:`level`: lit at all, or dark."""
        return self.level > 0.0

    @state.setter
    def state(self, value: bool) -> None:
        self.level = 1.0 if value else 0.0

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Draw the LED at its current brightness, with a matching glow and label."""
        cx, cy = self.rect.center
        r = max(4, min(self.rect.width, self.rect.height) // 2 - 2)

        # Resolved LED color (U36) or the theme default; THEME is read here, at
        # draw time, never captured at import (U6).
        on_color = self._on_color or THEME.led_on
        # A colored LED tints its dark epoxy faintly toward its own hue (the
        # "colored lens" look); an uncolored one keeps the plain theme off-color.
        off_color = lerp_rgb(THEME.led_off, on_color, 0.12) if self._on_color else THEME.led_off
        k = _perceptual(self.level)

        if k > 0.0:
            # Glow takes the LED's own color at an alpha that tracks brightness,
            # so a dim LED gets a faint halo instead of the old fixed red one.
            glow = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (*on_color, round(50 * k)), (r * 2, r * 2), r * 2)
            surface.blit(glow, (cx - r * 2, cy - r * 2))
        pygame.draw.circle(surface, lerp_rgb(off_color, on_color, k), (cx, cy), r)

        pygame.draw.circle(surface, WHITE, (cx, cy), r, 1)

        lbl = font.render(self.label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(centerx=cx, top=self.rect.bottom + 1))

    @property
    def tooltip_extra(self) -> list[tuple[str, str]]:
        """Hover rows for the measured duty cycle (U9), once it is not binary."""
        if self.level in (0.0, 1.0):
            return []
        return [("Duty", f"{self.level * 100:.1f}%")]


class RGBLED(LED):
    """A tri-color LED puck: three measured channel duties mixed into one color.

    Subclasses :class:`LED` so it slots into ``FPGABoard.leds`` and every
    binary/level caller keeps working: :attr:`level` becomes a view over the
    brightest channel, and *setting* it drives all three channels equally (the
    honest white-mix reading of a binary "on").  The real interface is
    :meth:`set_channel` — per-channel linear duty in [0, 1] — which the
    simulation screen feeds through ``BoardDef.led_channels`` (U37).

    Rendering mixes per-channel γ-encoded duties (``px_c = 255 · duty_c^(1/γ)``,
    so (1, 1, 1) washes to white exactly like a real RGB LED), shown over the
    dark epoxy via a channelwise max — an off puck stays the theme's neutral.
    """

    #: Channel order matches ``BoardDef.led_channels``' ("r", "g", "b").
    _CHANNELS = ("r", "g", "b")

    def __init__(self, index: int, info: ComponentInfo | None = None) -> None:
        """Initialize the puck with its board index and optional metadata."""
        self.levels: list[float] = [0.0, 0.0, 0.0]
        super().__init__(index, info)  # sets .level -> routed through the setter

    @property
    def level(self) -> float:
        """Brightest channel, so LED's ``state``/tooltip gates keep working."""
        return max(self.levels)

    @level.setter
    def level(self, value: float) -> None:
        self.levels = [float(value)] * 3

    def set_channel(self, channel: str, level: float) -> None:
        """Set one channel's linear duty (``channel`` in ``"r" / "g" / "b"``)."""
        self.levels[self._CHANNELS.index(channel)] = float(level)

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Draw the puck at its mixed color, with a matching glow and label."""
        cx, cy = self.rect.center
        r = max(4, min(self.rect.width, self.rect.height) // 2 - 2)

        px = tuple(round(255 * _perceptual(lv)) for lv in self.levels)
        off = THEME.led_off  # THEME read at draw time, never captured (U6)
        shown = (max(off[0], px[0]), max(off[1], px[1]), max(off[2], px[2]))
        k = _perceptual(self.level)

        if k > 0.0:
            glow = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (*px, round(50 * k)), (r * 2, r * 2), r * 2)
            surface.blit(glow, (cx - r * 2, cy - r * 2))
        pygame.draw.circle(surface, shown, (cx, cy), r)

        pygame.draw.circle(surface, WHITE, (cx, cy), r, 1)

        lbl = font.render(self.label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(centerx=cx, top=self.rect.bottom + 1))

    @property
    def tooltip_extra(self) -> list[tuple[str, str]]:
        """Per-channel duty rows — always shown; the mix is the whole story."""
        return [
            (ch.upper(), f"{lv * 100:.0f}%")
            for ch, lv in zip(("r", "g", "b"), self.levels, strict=True)
        ]


class Switch(UIComponent):
    """A toggle switch – clicks flip the state."""

    _LABEL_PREFIX = "SW"

    def __init__(self, index: int, info: ComponentInfo | None = None) -> None:
        """Initialize the switch with its board index and optional component metadata."""
        super().__init__(index, info)
        self.state = False
        self.callback: Callable[[int, bool, ComponentInfo | None], None] | None = None

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Draw the toggle switch body, knob, and label."""
        color = THEME.switch_on if self.state else THEME.switch_off
        pygame.draw.rect(surface, color, self.rect, border_radius=4)
        pygame.draw.rect(surface, WHITE, self.rect, 2, border_radius=4)

        knob_h = self.rect.height // 2
        knob_y = self.rect.y + 2 if self.state else self.rect.bottom - knob_h - 2
        knob = pygame.Rect(self.rect.x + 3, knob_y, self.rect.width - 6, knob_h)
        pygame.draw.rect(surface, WHITE if self.state else GRAY, knob, border_radius=3)

        lbl = font.render(self.label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(centerx=self.rect.centerx, top=self.rect.bottom + 2))

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """Toggle the switch state if pos falls within its rect; return True on hit."""
        if self.rect.collidepoint(pos):
            self.state = not self.state
            if self.callback:
                self.callback(self.index, self.state, self.info)
            return True
        return False


class Button(UIComponent):
    """A momentary push-button – pressed while the mouse is held down."""

    _LABEL_PREFIX = "BTN"

    def __init__(self, index: int, info: ComponentInfo | None = None) -> None:
        """Initialize the button with its board index and optional component metadata."""
        super().__init__(index, info)
        self.pressed = False
        self.callback: Callable[[int, bool, ComponentInfo | None], None] | None = None

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Draw the push-button with a highlight when pressed, plus its label."""
        if self.pressed:
            inner = self.rect.inflate(-4, -4)
            pygame.draw.rect(surface, THEME.push_on, inner, border_radius=6)
        else:
            pygame.draw.rect(surface, THEME.push_off, self.rect, border_radius=6)
        pygame.draw.rect(surface, WHITE, self.rect, 2, border_radius=6)

        lbl = font.render(self.label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(centerx=self.rect.centerx, top=self.rect.bottom + 2))

    def handle_press(self, pos: tuple[int, int]) -> bool:
        """Mark the button as pressed if pos is within its rect; return True on hit."""
        if self.rect.collidepoint(pos):
            self.pressed = True
            if self.callback:
                self.callback(self.index, True, self.info)
            return True
        return False

    def handle_release(self) -> None:
        """Release the button and fire the callback if it was previously pressed."""
        if self.pressed:
            self.pressed = False
            if self.callback:
                self.callback(self.index, False, self.info)


class SevenSeg:
    """Draws one digit of a 7-segment display.

    Segment colors (``seg_on`` / ``seg_off`` / ``seg_bg`` / ``seg_bezel``) are
    read from THEME at draw time — never captured — so a set_theme() swap
    restyles the digits.
    """

    # Bit positions: {dp, g, f, e, d, c, b, a}
    _BIT: dict[str, int] = {
        "a": 0,
        "b": 1,
        "c": 2,
        "d": 3,
        "e": 4,
        "f": 5,
        "g": 6,
        "dp": 7,
    }

    def __init__(self, index: int, has_dp: bool = False) -> None:
        """Initialize the digit with its board index and whether a decimal point is present."""
        self.index = index
        self.has_dp = has_dp
        self.bits: int = 0
        #: Per-segment duty cycle, indexed by :data:`_BIT` (U9).  Segments are
        #: LEDs, so a time-multiplexed or PWM-driven digit renders at its real
        #: brightness rather than snapping to fully-on/fully-off.
        self.levels: list[float] = [0.0] * 8
        self.rect = pygame.Rect(0, 0, 48, 76)

    def set_bits(self, value8: int) -> None:
        """Set from an 8-bit value {dp,g,f,e,d,c,b,a}, active-high (fully on or off)."""
        self.bits = value8 & 0xFF
        self.levels = [1.0 if self.bits & (1 << i) else 0.0 for i in range(8)]

    def set_levels(self, levels: Sequence[float]) -> None:
        """Set per-segment duty cycles, ordered like :data:`_BIT` (``a`` lowest).

        ``bits`` follows along as the binary view (any lit segment reads as on),
        so callers that only care whether a segment is active keep working.
        """
        self.levels = [max(0.0, min(1.0, v)) for v in levels[:8]]
        self.levels += [0.0] * (8 - len(self.levels))
        self.bits = sum(1 << i for i, v in enumerate(self.levels) if v > 0.0)

    def _seg(self, name: str) -> bool:
        """Return True when the named segment is lit at all."""
        return self.levels[self._BIT[name]] > 0.0

    def draw(self, surface: pygame.Surface) -> None:
        """Draw the digit onto *surface* using the current bit pattern."""
        dw, dh = self.rect.width, self.rect.height
        thick = max(3, int(dw * 0.12))
        gap = max(2, int(dw * 0.06))
        inner = max(1, dw - 2 * gap - 2 * thick)
        half = dh // 2
        x0, y0 = self.rect.topleft

        pygame.draw.rect(surface, THEME.seg_bg, self.rect, border_radius=3)
        pygame.draw.rect(surface, THEME.seg_bezel, self.rect, width=1, border_radius=3)

        def color(n: str) -> tuple[int, int, int]:
            # THEME read at draw time (U6); same perceptual ramp as the LEDs.
            return lerp_rgb(THEME.seg_off, THEME.seg_on, _perceptual(self.levels[self._BIT[n]]))

        def hrect(x: int, y: int, w: int, h: int, n: str) -> None:
            c = color(n)
            pts: list[tuple[int, int]] = [
                (x + h // 2, y),
                (x + w - h // 2, y),
                (x + w, y + h // 2),
                (x + w - h // 2, y + h),
                (x + h // 2, y + h),
                (x, y + h // 2),
            ]
            pygame.draw.polygon(surface, c, pts)

        def vrect(x: int, y: int, w: int, h: int, n: str) -> None:
            c = color(n)
            pts: list[tuple[int, int]] = [
                (x + w // 2, y),
                (x + w, y + w // 2),
                (x + w, y + h - w // 2),
                (x + w // 2, y + h),
                (x, y + h - w // 2),
                (x, y + w // 2),
            ]
            pygame.draw.polygon(surface, c, pts)

        ax = x0 + gap + thick
        hrect(ax, y0 + gap, inner, thick, "a")
        vrect(x0 + dw - gap - thick, y0 + gap + thick, thick, half - 2 * gap, "b")
        vrect(x0 + dw - gap - thick, y0 + half + gap, thick, half - 2 * gap - thick, "c")
        hrect(ax, y0 + dh - gap - thick, inner, thick, "d")
        vrect(x0 + gap, y0 + half + gap, thick, half - 2 * gap - thick, "e")
        vrect(x0 + gap, y0 + gap + thick, thick, half - 2 * gap, "f")
        hrect(ax, y0 + half - thick // 2, inner, thick, "g")

        if self.has_dp:
            r = max(2, thick // 2)
            pygame.draw.circle(surface, color("dp"), (x0 + dw + r + 2, y0 + dh - r - 2), r)

        lbl_sz = max(8, int(dh * 0.18))
        lbl = _get_font(lbl_sz).render(str(self.index), True, THEME.seg_digit_label)
        surface.blit(lbl, (x0 + dw // 2 - lbl.get_width() // 2, y0 + dh + 2))
