"""
FPGA Board Simulator - Pygame-based graphical interface.

Provides interactive switches, buttons, and LEDs that auto-arrange
to fit the window. Supports resize and per-component callbacks.
"""

import math
import pygame
import sys

# ── Colours ──────────────────────────────────────────────────────────
BG_GREEN = (34, 139, 34)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED_ON = (255, 30, 30)
RED_OFF = (80, 0, 0)
GRAY = (180, 180, 180)
DARK_GRAY = (80, 80, 80)
YELLOW = (255, 230, 50)
BLUE_ON = (80, 140, 255)
BLUE_OFF = (40, 50, 80)


# ── Component classes ────────────────────────────────────────────────

class LED:
    """A read-only indicator controlled via FPGABoard.set_led()."""

    def __init__(self, index):
        self.index = index
        self.state = False
        self.rect = pygame.Rect(0, 0, 0, 0)

    def draw(self, surface, font):
        cx, cy = self.rect.center
        r = max(4, min(self.rect.width, self.rect.height) // 2 - 2)

        if self.state:
            # soft glow
            glow = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (255, 40, 40, 50), (r * 2, r * 2), r * 2)
            surface.blit(glow, (cx - r * 2, cy - r * 2))
            pygame.draw.circle(surface, RED_ON, (cx, cy), r)
        else:
            pygame.draw.circle(surface, RED_OFF, (cx, cy), r)

        pygame.draw.circle(surface, WHITE, (cx, cy), r, 1)

        label = font.render(str(self.index), True, WHITE)
        surface.blit(label, label.get_rect(centerx=cx, top=self.rect.bottom + 1))


class Switch:
    """A toggle switch – clicks flip the state."""

    def __init__(self, index):
        self.index = index
        self.state = False
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.callback = None

    def draw(self, surface, font):
        colour = BLUE_ON if self.state else BLUE_OFF
        pygame.draw.rect(surface, colour, self.rect, border_radius=4)
        pygame.draw.rect(surface, WHITE, self.rect, 2, border_radius=4)

        # slider knob
        knob_h = self.rect.height // 2
        if self.state:
            knob_y = self.rect.y + 2
        else:
            knob_y = self.rect.bottom - knob_h - 2
        knob = pygame.Rect(self.rect.x + 3, knob_y, self.rect.width - 6, knob_h)
        pygame.draw.rect(surface, WHITE if self.state else GRAY, knob, border_radius=3)

        label = font.render(f"SW{self.index}", True, WHITE)
        surface.blit(label, label.get_rect(centerx=self.rect.centerx, top=self.rect.bottom + 2))

    def handle_click(self, pos):
        if self.rect.collidepoint(pos):
            self.state = not self.state
            if self.callback:
                self.callback(self.index, self.state)
            return True
        return False


class Button:
    """A momentary push-button – pressed while the mouse is held down."""

    def __init__(self, index):
        self.index = index
        self.pressed = False
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.callback = None

    def draw(self, surface, font):
        if self.pressed:
            inner = self.rect.inflate(-4, -4)
            pygame.draw.rect(surface, YELLOW, inner, border_radius=6)
        else:
            pygame.draw.rect(surface, GRAY, self.rect, border_radius=6)
        pygame.draw.rect(surface, WHITE, self.rect, 2, border_radius=6)

        label = font.render(f"BTN{self.index}", True, WHITE)
        surface.blit(label, label.get_rect(centerx=self.rect.centerx, top=self.rect.bottom + 2))

    def handle_press(self, pos):
        if self.rect.collidepoint(pos):
            self.pressed = True
            if self.callback:
                self.callback(self.index, True)
            return True
        return False

    def handle_release(self):
        if self.pressed:
            self.pressed = False
            if self.callback:
                self.callback(self.index, False)


# ── Main board ───────────────────────────────────────────────────────

class FPGABoard:
    """
    Pygame window that renders an FPGA-style board.

    Parameters
    ----------
    num_switches : int   Number of toggle switches (0-12+).
    num_buttons  : int   Number of push-buttons (0-12+).
    num_leds     : int   Number of LEDs (0-64+).
    width, height: int   Initial window size (resizable).
    """

    def __init__(self, num_switches=8, num_buttons=4, num_leds=16,
                 width=1024, height=700):
        pygame.init()
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption("FPGA Simulator")
        self.clock = pygame.time.Clock()
        self.running = False

        # Create components (geometry set by _layout)
        self.leds = [LED(i) for i in range(num_leds)]
        self.buttons = [Button(i) for i in range(num_buttons)]
        self.switches = [Switch(i) for i in range(num_switches)]

        # Wire default print callbacks
        for sw in self.switches:
            sw.callback = lambda idx, st: print(f"Switch {idx}: {'ON' if st else 'OFF'}")
        for btn in self.buttons:
            btn.callback = lambda idx, st: print(f"Button {idx}: {'PRESSED' if st else 'RELEASED'}")

        self._layout()

    # ── public API ───────────────────────────────────────────────────

    def set_led(self, index: int, state: bool):
        """Turn an LED on or off by index."""
        if 0 <= index < len(self.leds):
            self.leds[index].state = bool(state)

    def set_switch_callback(self, callback):
        """Set callback for *all* switches.  Signature: callback(index, state)."""
        for sw in self.switches:
            sw.callback = callback

    def set_button_callback(self, callback):
        """Set callback for *all* buttons.  Signature: callback(index, pressed)."""
        for btn in self.buttons:
            btn.callback = callback

    def get_switch_state(self, index: int) -> bool:
        """Read the current state of a switch."""
        if 0 <= index < len(self.switches):
            return self.switches[index].state
        return False

    def run(self):
        """Enter the main loop (blocking)."""
        self.running = True
        while self.running:
            self._handle_events()
            self._draw()
            self.clock.tick(60)
        pygame.quit()

    # ── layout engine ────────────────────────────────────────────────

    def _layout(self):
        """Recompute component positions to fit the current window size."""
        w, h = self.width, self.height
        margin = 20
        title_h = 22          # space for each section title
        label_h = 18           # space for labels below components
        section_pad = 10       # gap between sections

        sections = []          # (name, items, weight)
        if self.leds:
            sections.append(("leds", self.leds, 3))
        if self.buttons:
            sections.append(("buttons", self.buttons, 1))
        if self.switches:
            sections.append(("switches", self.switches, 1))

        if not sections:
            return

        total_weight = sum(s[2] for s in sections)
        usable_h = h - 2 * margin - section_pad * (len(sections) - 1)

        y = margin
        for name, items, weight in sections:
            sec_h = usable_h * weight / total_weight
            content_h = sec_h - title_h - label_h
            self._place_items(items, margin, y + title_h, w - 2 * margin, content_h, name)
            y += sec_h + section_pad

    def _place_items(self, items, x0, y0, avail_w, avail_h, kind):
        n = len(items)
        if n == 0:
            return

        # Determine grid cols × rows to best fill the rectangle
        if kind == "leds":
            aspect = avail_w / max(1, avail_h)
            cols = max(1, round(math.sqrt(n * aspect)))
            cols = min(cols, n)
        else:
            cols = min(n, max(1, int(avail_w / 65)))
        rows = math.ceil(n / cols)

        cell_w = avail_w / cols
        cell_h = avail_h / max(1, rows)

        if kind == "leds":
            size = min(cell_w, cell_h) * 0.75
            size = max(10, min(size, 44))
        elif kind == "buttons":
            size_w = min(cell_w * 0.70, 90)
            size_h = min(cell_h * 0.60, 50)
        else:  # switches
            size_w = min(cell_w * 0.50, 44)
            size_h = min(cell_h * 0.65, 60)

        for i, item in enumerate(items):
            r = i // cols
            c = i % cols
            cx = x0 + c * cell_w + cell_w / 2
            cy = y0 + r * cell_h + cell_h / 2
            if kind == "leds":
                item.rect = pygame.Rect(cx - size / 2, cy - size / 2, size, size)
            else:
                item.rect = pygame.Rect(cx - size_w / 2, cy - size_h / 2, size_w, size_h)

    # ── events ───────────────────────────────────────────────────────

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.VIDEORESIZE:
                self.width, self.height = event.w, event.h
                self.screen = pygame.display.set_mode(
                    (self.width, self.height), pygame.RESIZABLE)
                self._layout()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for sw in self.switches:
                    sw.handle_click(event.pos)
                for btn in self.buttons:
                    btn.handle_press(event.pos)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                for btn in self.buttons:
                    btn.handle_release()

    # ── drawing ──────────────────────────────────────────────────────

    def _draw(self):
        self.screen.fill(BG_GREEN)

        font_size = max(10, min(14, self.height // 55))
        font = pygame.font.SysFont("consolas", font_size)
        title_font = pygame.font.SysFont("consolas", font_size + 4, bold=True)

        # Section titles
        if self.leds:
            t = title_font.render("LEDs", True, WHITE)
            self.screen.blit(t, (20, self.leds[0].rect.top - font_size - 10))
        if self.buttons:
            t = title_font.render("Buttons", True, WHITE)
            self.screen.blit(t, (20, self.buttons[0].rect.top - font_size - 14))
        if self.switches:
            t = title_font.render("Switches", True, WHITE)
            self.screen.blit(t, (20, self.switches[0].rect.top - font_size - 14))

        for led in self.leds:
            led.draw(self.screen, font)
        for btn in self.buttons:
            btn.draw(self.screen, font)
        for sw in self.switches:
            sw.draw(self.screen, font)

        pygame.display.flip()


# ── Entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    board = FPGABoard(num_switches=8, num_buttons=4, num_leds=16)

    # Demo: light up a few LEDs
    board.set_led(0, True)
    board.set_led(3, True)
    board.set_led(7, True)

    board.run()
