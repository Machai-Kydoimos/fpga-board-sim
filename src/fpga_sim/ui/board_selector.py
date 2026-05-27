"""BoardSelector screen: board picker with search, faceted filtering, and sorting."""

import pygame

from fpga_sim.board_loader import BoardDef
from fpga_sim.ui.constants import (
    SEL_BG,
    SEL_HOVER,
    SEL_ROW_A,
    SEL_ROW_B,
    WHITE,
    _ui_scale,
    get_font,
)

_CHIP_ACTIVE = (45, 110, 55)
_CHIP_INACTIVE = (50, 50, 60)
_CHIP_HOVER = (60, 75, 65)
_CHIP_TEXT = (200, 200, 210)
_CHIP_TEXT_ACTIVE = (230, 255, 230)
_SORT_BG = (50, 55, 75)
_SORT_HOVER = (65, 70, 90)
_SORT_TEXT = (180, 190, 220)
_DROPDOWN_BG = (42, 42, 55)
_DROPDOWN_HOVER = (55, 65, 55)
_DROPDOWN_BORDER = (70, 70, 85)

_SORT_OPTIONS: list[tuple[str, str]] = [
    ("name", "Name"),
    ("vendor", "Vendor"),
    ("leds", "LEDs ↓"),
    ("switches", "Switches ↓"),
    ("buttons", "Buttons ↓"),
    ("7seg", "7-seg ↓"),
    ("total", "Total ↓"),
]
_SORT_KEYS = {k for k, _ in _SORT_OPTIONS}

_COMPONENT_CHIPS: list[tuple[str, str]] = [
    ("has_leds", "Has LEDs"),
    ("has_switches", "Has Switches"),
    ("has_buttons", "Has Buttons"),
    ("has_7seg", "Has 7-seg"),
]

_VENDOR_CHIP_THRESHOLD = 3


class BoardSelector:
    """Full-screen picker.  Returns the chosen BoardDef, or None on quit."""

    def __init__(
        self,
        boards: list[BoardDef],
        screen: pygame.Surface,
        preselect_class: str = "",
        preselect_source: str = "",
        initial_sort: str = "",
        initial_component_filters: list[str] | None = None,
        initial_vendor_filters: list[str] | None = None,
    ) -> None:
        """Initialise the selector with a board list and optional pre-selected class name."""
        self.boards = boards
        self.screen = screen
        self.width, self.height = screen.get_size()
        self.scroll = 0
        self.hovered = -1
        self.filter_text = ""

        # Faceted filter state
        self._component_filters: set[str] = set(initial_component_filters or [])
        self._vendor_filters: set[str] = set(initial_vendor_filters or [])
        self._sort_key = initial_sort if initial_sort in _SORT_KEYS else "name"
        self._sort_open = False

        # Compute vendor chips from board data
        vendor_counts: dict[str, int] = {}
        for b in boards:
            v = b.vendor or "Other"
            vendor_counts[v] = vendor_counts.get(v, 0) + 1
        self._vendors = sorted(
            v
            for v, c in vendor_counts.items()
            if c >= _VENDOR_CHIP_THRESHOLD and v != "Other"
        )
        named = set(self._vendors)
        self._has_other = any((b.vendor or "Other") not in named for b in boards)

        # Click targets populated by _draw(), consumed by _hover()/_click()
        self._chip_rects: list[tuple[pygame.Rect, str, str]] = []
        self._sort_rect = pygame.Rect(0, 0, 0, 0)
        self._sort_item_rects: list[pygame.Rect] = []
        self._hovered_chip: str | None = None
        self._hovered_sort_item = -1

        # Detect which board names appear more than once (from different sources)
        name_counts: dict[str, int] = {}
        for b in boards:
            name_counts[b.name] = name_counts.get(b.name, 0) + 1
        self._duplicate_names = {n for n, c in name_counts.items() if c > 1}

        if preselect_class:
            visible = self._filtered()
            idx = next(
                (
                    i
                    for i, b in enumerate(visible)
                    if b.class_name == preselect_class
                    and b.source == preselect_source
                ),
                -1,
            )
            if idx < 0:
                idx = next(
                    (
                        i
                        for i, b in enumerate(visible)
                        if b.class_name == preselect_class
                    ),
                    -1,
                )
            if idx >= 0:
                self.hovered = idx
                viewport_h = self.height - self._hdr
                self.scroll = max(
                    0, idx * self.row_h - viewport_h // 2 + self.row_h // 2
                )

    @property
    def sort_key(self) -> str:
        """The current sort key (persisted across sessions by the caller)."""
        return self._sort_key

    @property
    def component_filters(self) -> list[str]:
        """Active component filter keys, sorted for deterministic serialization."""
        return sorted(self._component_filters)

    @property
    def vendor_filters(self) -> list[str]:
        """Active vendor filter keys, sorted for deterministic serialization."""
        return sorted(self._vendor_filters)

    @property
    def row_h(self) -> int:
        """Return the pixel height of each board-list row."""
        return max(48, round(48 * _ui_scale(self.width, self.height)))

    @property
    def _hdr(self) -> int:
        s = _ui_scale(self.width, self.height)
        title_h = max(18, round(28 * s))
        chip_h = max(16, round(18 * s))
        return 8 + title_h + 4 + 24 + 10 + chip_h + 3 + chip_h + 8

    @property
    def _has_active_filters(self) -> bool:
        return bool(
            self.filter_text or self._component_filters or self._vendor_filters
        )

    def _filtered(self) -> list[BoardDef]:
        boards = self.boards

        if self.filter_text:
            ft = self.filter_text.lower()
            boards = [
                b
                for b in boards
                if ft in b.name.lower() or ft in b.class_name.lower()
            ]

        if "has_leds" in self._component_filters:
            boards = [b for b in boards if b.leds]
        if "has_switches" in self._component_filters:
            boards = [b for b in boards if b.switches]
        if "has_buttons" in self._component_filters:
            boards = [b for b in boards if b.buttons]
        if "has_7seg" in self._component_filters:
            boards = [b for b in boards if b.seven_seg]

        if self._vendor_filters:
            named = set(self._vendors)
            boards = [
                b
                for b in boards
                if (b.vendor or "Other") in self._vendor_filters
                or (
                    "Other" in self._vendor_filters
                    and (b.vendor or "Other") not in named
                )
            ]

        if self._sort_key == "vendor":
            boards = sorted(boards, key=lambda b: (b.vendor or "zzz", b.name))
        elif self._sort_key == "leds":
            boards = sorted(boards, key=lambda b: len(b.leds), reverse=True)
        elif self._sort_key == "switches":
            boards = sorted(
                boards, key=lambda b: len(b.switches), reverse=True
            )
        elif self._sort_key == "buttons":
            boards = sorted(
                boards, key=lambda b: len(b.buttons), reverse=True
            )
        elif self._sort_key == "7seg":
            boards = sorted(
                boards,
                key=lambda b: b.seven_seg.num_digits if b.seven_seg else 0,
                reverse=True,
            )
        elif self._sort_key == "total":
            boards = sorted(
                boards,
                key=lambda b: len(b.leds) + len(b.buttons) + len(b.switches),
                reverse=True,
            )

        return boards

    def run(self, clock: pygame.time.Clock) -> BoardDef | None:
        """Run the event loop and return the selected BoardDef, or None on quit."""
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return None
                elif ev.type == pygame.WINDOWRESIZED:
                    self.width, self.height = ev.x, ev.y
                    self.scroll = 0
                    self._sort_open = False
                elif ev.type == pygame.MOUSEMOTION:
                    self._hover(ev.pos)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        result = self._click(ev.pos)
                        if result is not None:
                            return result
                    elif ev.button == 4:
                        step = max(20, round(self.row_h * 3))
                        self.scroll = max(0, self.scroll - step)
                    elif ev.button == 5:
                        step = max(20, round(self.row_h * 3))
                        self.scroll += step
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        if self._sort_open:
                            self._sort_open = False
                        else:
                            return None
                    elif ev.key == pygame.K_BACKSPACE:
                        self._sort_open = False
                        self.filter_text = self.filter_text[:-1]
                        self.scroll = 0
                    elif ev.unicode and ev.unicode.isprintable():
                        self._sort_open = False
                        self.filter_text += ev.unicode
                        self.scroll = 0

            self._draw()
            clock.tick(30)

    def _hover(self, pos: tuple[int, int]) -> None:
        if self._sort_open:
            self._hovered_sort_item = -1
            for i, rect in enumerate(self._sort_item_rects):
                if rect.collidepoint(pos):
                    self._hovered_sort_item = i
                    break
            self.hovered = -1
            self._hovered_chip = None
            return

        self._hovered_chip = None
        for rect, _, key in self._chip_rects:
            if rect.collidepoint(pos):
                self._hovered_chip = key
                self.hovered = -1
                return
        if self._sort_rect.collidepoint(pos):
            self._hovered_chip = "_sort"
            self.hovered = -1
            return

        hdr = self._hdr
        _, y = pos
        if y < hdr:
            self.hovered = -1
            return
        idx = (y - hdr + self.scroll) // self.row_h
        f = self._filtered()
        self.hovered = idx if 0 <= idx < len(f) else -1

    def _click(self, pos: tuple[int, int]) -> BoardDef | None:
        if self._sort_open:
            for i, rect in enumerate(self._sort_item_rects):
                if rect.collidepoint(pos):
                    self._sort_key = _SORT_OPTIONS[i][0]
                    self._sort_open = False
                    return None
            self._sort_open = False
            return None

        for rect, chip_type, key in self._chip_rects:
            if rect.collidepoint(pos):
                target = (
                    self._component_filters
                    if chip_type == "component"
                    else self._vendor_filters
                )
                if key in target:
                    target.discard(key)
                else:
                    target.add(key)
                self.scroll = 0
                self.hovered = -1
                return None

        if self._sort_rect.collidepoint(pos):
            self._sort_open = True
            return None

        self._hover(pos)
        f = self._filtered()
        if 0 <= self.hovered < len(f):
            return f[self.hovered]
        return None

    def _draw_chip(
        self,
        x: int,
        y: int,
        label: str,
        active: bool,
        hovered: bool,
        chip_h: int,
        font: pygame.font.Font,
    ) -> pygame.Rect:
        text_color = _CHIP_TEXT_ACTIVE if active else _CHIP_TEXT
        text_surf = font.render(label, True, text_color)
        chip_w = text_surf.get_width() + 12
        bg = _CHIP_ACTIVE if active else (_CHIP_HOVER if hovered else _CHIP_INACTIVE)
        rect = pygame.Rect(x, y, chip_w, chip_h)
        pygame.draw.rect(self.screen, bg, rect, border_radius=3)
        self.screen.blit(
            text_surf, (x + 6, y + (chip_h - text_surf.get_height()) // 2)
        )
        return rect

    def _draw(self) -> None:
        self.screen.fill(SEL_BG)
        s = _ui_scale(self.width, self.height)
        title_f = get_font(max(14, round(22 * s)), bold=True)
        item_f = get_font(max(11, round(15 * s)))
        detail_f = get_font(max(9, round(11 * s)))
        chip_f = detail_f

        hdr = self._hdr
        filtered = self._filtered()
        max_scroll = max(0, len(filtered) * self.row_h - (self.height - hdr))
        self.scroll = min(self.scroll, max_scroll)
        chip_h = max(16, round(18 * s))
        chip_gap = max(4, round(6 * s))

        # Board list
        for i, b in enumerate(filtered):
            y = hdr + i * self.row_h - self.scroll
            if y + self.row_h < hdr or y > self.height:
                continue
            bg = (
                SEL_HOVER
                if i == self.hovered
                else (SEL_ROW_A if i % 2 == 0 else SEL_ROW_B)
            )
            pygame.draw.rect(
                self.screen, bg, (10, y, self.width - 20, self.row_h - 2)
            )
            nm = item_f.render(b.name, True, (220, 220, 255))
            self.screen.blit(nm, (20, y + 4))
            detail = b.summary
            if b.source and b.name in self._duplicate_names:
                detail = f"{detail}  ·  {b.source}"
            sm = detail_f.render(detail, True, (150, 150, 150))
            self.screen.blit(sm, (20, y + 4 + item_f.get_height() + 2))

        # Header overlay (hides items that scrolled behind header)
        pygame.draw.rect(self.screen, SEL_BG, (0, 0, self.width, hdr))
        title = title_f.render(
            "FPGA Simulator — Select Board", True, WHITE
        )
        self.screen.blit(title, (20, 8))

        # Filter text box
        filter_y = 8 + title_f.get_height() + 4
        stxt = (
            f"Filter: {self.filter_text}_"
            if self.filter_text
            else "Type to filter boards..."
        )
        srch = item_f.render(stxt, True, (180, 180, 180))
        pygame.draw.rect(
            self.screen,
            (50, 50, 60),
            (20, filter_y, self.width - 140, 24),
            border_radius=3,
        )
        self.screen.blit(srch, (26, filter_y + 2))

        # Board count
        if self._has_active_filters:
            cnt_text = f"{len(filtered)} of {len(self.boards)} boards"
        else:
            cnt_text = f"{len(filtered)} boards"
        cnt = detail_f.render(cnt_text, True, (120, 120, 120))
        self.screen.blit(
            cnt, (self.width - cnt.get_width() - 20, filter_y + 4)
        )

        # Component filter chips
        chip1_y = filter_y + 34
        chip_rects: list[tuple[pygame.Rect, str, str]] = []
        x = 20
        for key, label in _COMPONENT_CHIPS:
            active = key in self._component_filters
            hovered = self._hovered_chip == key
            rect = self._draw_chip(
                x, chip1_y, label, active, hovered, chip_h, chip_f
            )
            chip_rects.append((rect, "component", key))
            x = rect.right + chip_gap

        # Sort dropdown trigger (right-aligned on component chip row)
        active_label = next(
            lb for k, lb in _SORT_OPTIONS if k == self._sort_key
        )
        arrow = "▴" if self._sort_open else "▾"
        sort_label = f"Sort: {active_label} {arrow}"
        sort_surf = chip_f.render(sort_label, True, _SORT_TEXT)
        sort_w = sort_surf.get_width() + 16
        sort_x = self.width - sort_w - 20
        sort_hovered = self._hovered_chip == "_sort"
        sort_bg = (
            _SORT_HOVER if (sort_hovered or self._sort_open) else _SORT_BG
        )
        self._sort_rect = pygame.Rect(sort_x, chip1_y, sort_w, chip_h)
        pygame.draw.rect(
            self.screen, sort_bg, self._sort_rect, border_radius=3
        )
        self.screen.blit(
            sort_surf,
            (sort_x + 8, chip1_y + (chip_h - sort_surf.get_height()) // 2),
        )

        # Vendor filter chips
        chip2_y = chip1_y + chip_h + 3
        x = 20
        for vendor in self._vendors:
            active = vendor in self._vendor_filters
            hovered = self._hovered_chip == vendor
            rect = self._draw_chip(
                x, chip2_y, vendor, active, hovered, chip_h, chip_f
            )
            chip_rects.append((rect, "vendor", vendor))
            x = rect.right + chip_gap
        if self._has_other:
            active = "Other" in self._vendor_filters
            hovered = self._hovered_chip == "Other"
            rect = self._draw_chip(
                x, chip2_y, "Other", active, hovered, chip_h, chip_f
            )
            chip_rects.append((rect, "vendor", "Other"))

        self._chip_rects = chip_rects

        # Sort dropdown menu (drawn last so it overlays everything)
        if self._sort_open:
            menu_item_h = chip_h + 2
            item_surfs = [
                chip_f.render(lb, True, _CHIP_TEXT) for _, lb in _SORT_OPTIONS
            ]
            max_text_w = max(sf.get_width() for sf in item_surfs)
            menu_w = max(self._sort_rect.w, max_text_w + 24)
            menu_x = max(0, self._sort_rect.right - menu_w)
            menu_y = self._sort_rect.bottom + 2
            menu_h = len(_SORT_OPTIONS) * menu_item_h + 4

            menu_rect = pygame.Rect(menu_x, menu_y, menu_w, menu_h)
            pygame.draw.rect(
                self.screen, _DROPDOWN_BG, menu_rect, border_radius=4
            )
            pygame.draw.rect(
                self.screen,
                _DROPDOWN_BORDER,
                menu_rect,
                width=1,
                border_radius=4,
            )

            sort_item_rects: list[pygame.Rect] = []
            for i, (key, label) in enumerate(_SORT_OPTIONS):
                iy = menu_y + 2 + i * menu_item_h
                ir = pygame.Rect(menu_x + 2, iy, menu_w - 4, menu_item_h)
                is_active = key == self._sort_key
                is_hovered = i == self._hovered_sort_item
                if is_active:
                    pygame.draw.rect(
                        self.screen, _CHIP_ACTIVE, ir, border_radius=2
                    )
                elif is_hovered:
                    pygame.draw.rect(
                        self.screen, _DROPDOWN_HOVER, ir, border_radius=2
                    )
                tc = _CHIP_TEXT_ACTIVE if is_active else _CHIP_TEXT
                ts = chip_f.render(label, True, tc)
                self.screen.blit(
                    ts, (ir.x + 8, iy + (menu_item_h - ts.get_height()) // 2)
                )
                sort_item_rects.append(ir)
            self._sort_item_rects = sort_item_rects
        else:
            self._sort_item_rects = []

        pygame.display.flip()
