"""Low-level UI components: FPGAChip, LED, Switch, Button.

These are the building blocks placed on the board canvas by FPGABoard.
"""

from collections.abc import Callable

import pygame

from fpga_sim.board_loader import ComponentInfo
from fpga_sim.ui.constants import (
    BLUE_OFF,
    BLUE_ON,
    GRAY,
    RED_OFF,
    RED_ON,
    WHITE,
    YELLOW,
)
from fpga_sim.ui.constants import (
    get_font as _get_font,
)

# ── Component classes ────────────────────────────────────────────────


class FPGAChip:
    """Visual representation of the FPGA IC package on the board."""

    _VENDOR_COLORS = {
        "Xilinx": (20, 60, 140),
        "Intel": (0, 90, 50),
        "Lattice": (90, 20, 90),
        "QuickLogic": (130, 60, 0),
        "Gowin": (70, 70, 0),
    }
    _BORDER_COLOR = (180, 180, 180)
    _DEVICE_COLOR = (200, 200, 200)
    _PACKAGE_COLOR = (150, 150, 150)
    _CLOCK_COLOR = (120, 200, 120)
    _PIN_COLOR = (120, 120, 120)
    _PIN_LENGTH = 5

    def __init__(
        self, vendor: str = "", device: str = "", package: str = "", clock_hz: float = 0.0
    ) -> None:
        """Initialise the chip with optional vendor, device, package, and clock metadata."""
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
        """Draw the FPGA chip package with vendor colour, pin marks, and text labels."""
        if self.rect.width < 20:
            return
        r = self.rect
        color = self._VENDOR_COLORS.get(self.vendor, (40, 40, 40))

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
                self._DEVICE_COLOR,
            ),
            (
                self.package.upper(),
                self._PACKAGE_COLOR,
            ),
        ]
        if self.clock_hz:
            lines.append((self._fmt_clock(self.clock_hz), self._CLOCK_COLOR))
        active = [(t, c) for t, c in lines if t]
        offset = -(len(active) - 1) / 2 * line_h
        for text, colour in active:
            s = font.render(text, True, colour)
            surface.blit(s, s.get_rect(centerx=cx, centery=cy + offset))
            offset += line_h

    def _draw_pin_marks(self, surface: pygame.Surface, r: pygame.Rect) -> None:
        color = self._PIN_COLOR
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


class LED:
    """A read-only indicator controlled via FPGABoard.set_led()."""

    def __init__(self, index: int, info: ComponentInfo | None = None) -> None:
        """Initialise the LED with its board index and optional component metadata."""
        self.index = index
        self.info = info
        self.state = False
        self.rect = pygame.Rect(0, 0, 0, 0)

    @property
    def label(self) -> str:
        """Human-readable label derived from ComponentInfo or the LED index."""
        return self.info.display_name if self.info else f"LED{self.index}"

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Draw the LED circle with glow effect when lit, plus its label."""
        cx, cy = self.rect.center
        r = max(4, min(self.rect.width, self.rect.height) // 2 - 2)

        if self.state:
            glow = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (255, 40, 40, 50), (r * 2, r * 2), r * 2)
            surface.blit(glow, (cx - r * 2, cy - r * 2))
            pygame.draw.circle(surface, RED_ON, (cx, cy), r)
        else:
            pygame.draw.circle(surface, RED_OFF, (cx, cy), r)

        pygame.draw.circle(surface, WHITE, (cx, cy), r, 1)

        lbl = font.render(self.label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(centerx=cx, top=self.rect.bottom + 1))


class Switch:
    """A toggle switch – clicks flip the state."""

    def __init__(self, index: int, info: ComponentInfo | None = None) -> None:
        """Initialise the switch with its board index and optional component metadata."""
        self.index = index
        self.info = info
        self.state = False
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.callback: Callable[[int, bool, ComponentInfo | None], None] | None = None

    @property
    def label(self) -> str:
        """Human-readable label derived from ComponentInfo or the switch index."""
        return self.info.display_name if self.info else f"SW{self.index}"

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Draw the toggle switch body, knob, and label."""
        colour = BLUE_ON if self.state else BLUE_OFF
        pygame.draw.rect(surface, colour, self.rect, border_radius=4)
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


class Button:
    """A momentary push-button – pressed while the mouse is held down."""

    def __init__(self, index: int, info: ComponentInfo | None = None) -> None:
        """Initialise the button with its board index and optional component metadata."""
        self.index = index
        self.info = info
        self.pressed = False
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.callback: Callable[[int, bool, ComponentInfo | None], None] | None = None

    @property
    def label(self) -> str:
        """Human-readable label derived from ComponentInfo or the button index."""
        return self.info.display_name if self.info else f"BTN{self.index}"

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Draw the push-button with a highlight when pressed, plus its label."""
        if self.pressed:
            inner = self.rect.inflate(-4, -4)
            pygame.draw.rect(surface, YELLOW, inner, border_radius=6)
        else:
            pygame.draw.rect(surface, GRAY, self.rect, border_radius=6)
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
    """Draws one digit of a 7-segment display."""

    SEG_ON: tuple[int, int, int] = (255, 140, 0)  # amber
    SEG_OFF: tuple[int, int, int] = (45, 25, 5)  # dark amber (ghost segments)
    BG: tuple[int, int, int] = (15, 15, 15)

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
        """Initialise the digit with its board index and whether a decimal point is present."""
        self.index = index
        self.has_dp = has_dp
        self.bits: int = 0
        self.rect = pygame.Rect(0, 0, 48, 76)

    def set_bits(self, value8: int) -> None:
        """Set from an 8-bit value {dp,g,f,e,d,c,b,a}, active-high."""
        self.bits = value8 & 0xFF

    def _seg(self, name: str) -> bool:
        """Return True when the named segment is active in the current bit pattern."""
        return bool(self.bits & (1 << self._BIT[name]))

    def draw(self, surface: pygame.Surface) -> None:
        """Draw the digit onto *surface* using the current bit pattern."""
        dw, dh = self.rect.width, self.rect.height
        thick = max(3, int(dw * 0.12))
        gap = max(2, int(dw * 0.06))
        inner = max(1, dw - 2 * gap - 2 * thick)
        half = dh // 2
        x0, y0 = self.rect.topleft

        pygame.draw.rect(surface, self.BG, self.rect, border_radius=3)
        pygame.draw.rect(surface, (5, 5, 5), self.rect, width=1, border_radius=3)

        def colour(n: str) -> tuple[int, int, int]:
            return self.SEG_ON if self._seg(n) else self.SEG_OFF

        def hrect(x: int, y: int, w: int, h: int, n: str) -> None:
            c = colour(n)
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
            c = colour(n)
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
            pygame.draw.circle(surface, colour("dp"), (x0 + dw + r + 2, y0 + dh - r - 2), r)

        lbl_sz = max(8, int(dh * 0.18))
        lbl = _get_font(lbl_sz).render(str(self.index), True, (90, 90, 90))
        surface.blit(lbl, (x0 + dw // 2 - lbl.get_width() // 2, y0 + dh + 2))
