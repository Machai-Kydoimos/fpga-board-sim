"""
FPGA Board Simulator - Pygame-based graphical interface.

Provides interactive switches, buttons, and LEDs that auto-arrange
to fit the window.  When amaranth-boards definitions are available
(git submodule), a board selector lets you pick a real board whose
resources (names, pins, connectors) are reflected in the UI.
"""

import math
import pygame
import sys

from board_loader import (
    discover_boards, get_default_boards_path, BoardDef, ComponentInfo,
)

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
SEL_BG = (30, 30, 40)
SEL_ROW_A = (40, 40, 50)
SEL_ROW_B = (35, 35, 45)
SEL_HOVER = (50, 70, 50)


# ── Component classes ────────────────────────────────────────────────

class LED:
    """A read-only indicator controlled via FPGABoard.set_led()."""

    def __init__(self, index, info=None):
        self.index = index
        self.info = info
        self.state = False
        self.rect = pygame.Rect(0, 0, 0, 0)

    @property
    def label(self):
        return self.info.display_name if self.info else f"LED{self.index}"

    def draw(self, surface, font):
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

    def __init__(self, index, info=None):
        self.index = index
        self.info = info
        self.state = False
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.callback = None

    @property
    def label(self):
        return self.info.display_name if self.info else f"SW{self.index}"

    def draw(self, surface, font):
        colour = BLUE_ON if self.state else BLUE_OFF
        pygame.draw.rect(surface, colour, self.rect, border_radius=4)
        pygame.draw.rect(surface, WHITE, self.rect, 2, border_radius=4)

        knob_h = self.rect.height // 2
        knob_y = self.rect.y + 2 if self.state else self.rect.bottom - knob_h - 2
        knob = pygame.Rect(self.rect.x + 3, knob_y, self.rect.width - 6, knob_h)
        pygame.draw.rect(surface, WHITE if self.state else GRAY, knob, border_radius=3)

        lbl = font.render(self.label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(centerx=self.rect.centerx, top=self.rect.bottom + 2))

    def handle_click(self, pos):
        if self.rect.collidepoint(pos):
            self.state = not self.state
            if self.callback:
                self.callback(self.index, self.state, self.info)
            return True
        return False


class Button:
    """A momentary push-button – pressed while the mouse is held down."""

    def __init__(self, index, info=None):
        self.index = index
        self.info = info
        self.pressed = False
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.callback = None

    @property
    def label(self):
        return self.info.display_name if self.info else f"BTN{self.index}"

    def draw(self, surface, font):
        if self.pressed:
            inner = self.rect.inflate(-4, -4)
            pygame.draw.rect(surface, YELLOW, inner, border_radius=6)
        else:
            pygame.draw.rect(surface, GRAY, self.rect, border_radius=6)
        pygame.draw.rect(surface, WHITE, self.rect, 2, border_radius=6)

        lbl = font.render(self.label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(centerx=self.rect.centerx, top=self.rect.bottom + 2))

    def handle_press(self, pos):
        if self.rect.collidepoint(pos):
            self.pressed = True
            if self.callback:
                self.callback(self.index, True, self.info)
            return True
        return False

    def handle_release(self):
        if self.pressed:
            self.pressed = False
            if self.callback:
                self.callback(self.index, False, self.info)


# ── Board selector ───────────────────────────────────────────────────

class BoardSelector:
    """Full-screen picker.  Returns the chosen BoardDef, or None on quit."""

    def __init__(self, boards, screen):
        self.boards = boards
        self.screen = screen
        self.width, self.height = screen.get_size()
        self.scroll = 0
        self.hovered = -1
        self.row_h = 48
        self.filter_text = ""

    def _filtered(self):
        if not self.filter_text:
            return self.boards
        ft = self.filter_text.lower()
        return [b for b in self.boards
                if ft in b.name.lower() or ft in b.class_name.lower()]

    def run(self, clock):
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return None
                elif ev.type == pygame.VIDEORESIZE:
                    self.width, self.height = ev.w, ev.h
                    self.screen = pygame.display.set_mode(
                        (self.width, self.height), pygame.RESIZABLE)
                elif ev.type == pygame.MOUSEMOTION:
                    self._hover(ev.pos)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        result = self._click(ev.pos)
                        if result is not None:
                            return result
                    elif ev.button == 4:
                        self.scroll = max(0, self.scroll - 30)
                    elif ev.button == 5:
                        self.scroll += 30
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return None
                    elif ev.key == pygame.K_BACKSPACE:
                        self.filter_text = self.filter_text[:-1]
                        self.scroll = 0
                    elif ev.unicode and ev.unicode.isprintable():
                        self.filter_text += ev.unicode
                        self.scroll = 0

            self._draw()
            clock.tick(30)

    def _hover(self, pos):
        hdr = 80
        _, y = pos
        if y < hdr:
            self.hovered = -1
            return
        idx = (y - hdr + self.scroll) // self.row_h
        f = self._filtered()
        self.hovered = idx if 0 <= idx < len(f) else -1

    def _click(self, pos):
        self._hover(pos)
        f = self._filtered()
        if 0 <= self.hovered < len(f):
            return f[self.hovered]
        return None

    def _draw(self):
        self.screen.fill(SEL_BG)
        title_f = pygame.font.SysFont("consolas", 22, bold=True)
        item_f = pygame.font.SysFont("consolas", 15)
        detail_f = pygame.font.SysFont("consolas", 11)

        hdr = 80
        filtered = self._filtered()

        for i, b in enumerate(filtered):
            y = hdr + i * self.row_h - self.scroll
            if y + self.row_h < hdr or y > self.height:
                continue
            bg = SEL_HOVER if i == self.hovered else (
                SEL_ROW_A if i % 2 == 0 else SEL_ROW_B)
            pygame.draw.rect(self.screen, bg,
                             (10, y, self.width - 20, self.row_h - 2))
            nm = item_f.render(b.name, True, (220, 220, 255))
            self.screen.blit(nm, (20, y + 4))
            sm = detail_f.render(b.summary, True, (150, 150, 150))
            self.screen.blit(sm, (20, y + 26))

        # Header overlay (hides items that scrolled behind header)
        pygame.draw.rect(self.screen, SEL_BG, (0, 0, self.width, hdr))
        title = title_f.render("FPGA Simulator \u2014 Select Board", True, WHITE)
        self.screen.blit(title, (20, 12))

        stxt = (f"Filter: {self.filter_text}_"
                if self.filter_text else "Type to filter boards...")
        srch = item_f.render(stxt, True, (180, 180, 180))
        pygame.draw.rect(self.screen, (50, 50, 60),
                         (20, 48, self.width - 140, 24), border_radius=3)
        self.screen.blit(srch, (26, 50))
        cnt = detail_f.render(f"{len(filtered)} boards", True, (120, 120, 120))
        self.screen.blit(cnt, (self.width - 100, 52))

        pygame.display.flip()


# ── Main board ───────────────────────────────────────────────────────

class FPGABoard:
    """
    Pygame window that renders an FPGA-style board.

    Parameters
    ----------
    board_def    : BoardDef or None
        If given, components are built from the board's resource list.
    num_switches, num_buttons, num_leds : int
        Fallback counts when no BoardDef is provided.
    width, height: int
        Initial window size (resizable).
    """

    def __init__(self, board_def=None, *,
                 num_switches=8, num_buttons=4, num_leds=16,
                 width=1024, height=700):
        self.board_def = board_def
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.running = False

        title = f"FPGA Simulator \u2013 {board_def.name}" if board_def else "FPGA Simulator"
        pygame.display.set_caption(title)

        if board_def:
            self.leds = [LED(i, info=c) for i, c in enumerate(board_def.leds)]
            self.buttons = [Button(i, info=c) for i, c in enumerate(board_def.buttons)]
            self.switches = [Switch(i, info=c) for i, c in enumerate(board_def.switches)]
        else:
            self.leds = [LED(i) for i in range(num_leds)]
            self.buttons = [Button(i) for i in range(num_buttons)]
            self.switches = [Switch(i) for i in range(num_switches)]

        # Default callbacks – print name + connector info
        def _sw_cb(idx, state, info):
            label = info.display_name if info else f"Switch {idx}"
            conn = f"  [{info.connector_str}]" if info else ""
            print(f"{label}: {'ON' if state else 'OFF'}{conn}")

        def _btn_cb(idx, pressed, info):
            label = info.display_name if info else f"Button {idx}"
            conn = f"  [{info.connector_str}]" if info else ""
            print(f"{label}: {'PRESSED' if pressed else 'RELEASED'}{conn}")

        for sw in self.switches:
            sw.callback = _sw_cb
        for btn in self.buttons:
            btn.callback = _btn_cb

        self._layout()

    # ── public API ───────────────────────────────────────────────────

    def set_led(self, index: int, state: bool):
        """Turn an LED on or off by index."""
        if 0 <= index < len(self.leds):
            self.leds[index].state = bool(state)

    def set_switch_callback(self, callback):
        """Set callback for *all* switches.  Signature: callback(index, state, info)."""
        for sw in self.switches:
            sw.callback = callback

    def set_button_callback(self, callback):
        """Set callback for *all* buttons.  Signature: callback(index, pressed, info)."""
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

    # ── layout engine ────────────────────────────────────────────────

    def _layout(self):
        """Recompute component positions to fit the current window size."""
        w, h = self.width, self.height
        margin = 20
        title_h = 22
        label_h = 18
        section_pad = 10

        sections = []
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
        else:
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

def main():
    pygame.init()
    width, height = 1024, 700

    boards = discover_boards(get_default_boards_path())

    if boards:
        screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption("FPGA Simulator")
        clock = pygame.time.Clock()

        chosen = BoardSelector(boards, screen).run(clock)
        if chosen is None:
            pygame.quit()
            return

        sim = FPGABoard(board_def=chosen, width=width, height=height)
    else:
        print("No amaranth-boards found; using generic board.")
        print("Run  git submodule update --init  to load board definitions.")
        sim = FPGABoard(width=width, height=height)

    sim.run()
    pygame.quit()


if __name__ == "__main__":
    main()
