"""Tests for BoardSelector: faceted filtering, sorting, and scroll behavior."""

from types import ModuleType

import pytest
from pygame.event import Event

from fpga_sim.board_loader import BoardDef, ComponentInfo, SevenSegDef
from fpga_sim.ui.board_selector import _SORT_OPTIONS, BoardSelector

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def screen(headless_pygame):
    return headless_pygame.display.set_mode((1024, 700))


def _leds(n: int) -> list[ComponentInfo]:
    return [ComponentInfo(kind="led", name="led", number=i) for i in range(n)]


def _switches(n: int) -> list[ComponentInfo]:
    return [ComponentInfo(kind="switch", name="switch", number=i) for i in range(n)]


def _buttons(n: int) -> list[ComponentInfo]:
    return [ComponentInfo(kind="button", name="button", number=i) for i in range(n)]


def _seg(digits: int) -> SevenSegDef:
    return SevenSegDef(
        num_digits=digits,
        has_dp=True,
        is_multiplexed=False,
        inverted=False,
        select_inverted=False,
    )


@pytest.fixture
def boards():
    """Seven boards with varied vendors and component counts.

    Xilinx x3 (meets _VENDOR_CHIP_THRESHOLD), others below threshold.
    """
    return [
        BoardDef(
            name="Alpha",
            class_name="AlphaPlatform",
            vendor="Xilinx",
            leds=_leds(4),
            buttons=_buttons(2),
            switches=[],
        ),
        BoardDef(
            name="Beta",
            class_name="BetaPlatform",
            vendor="Lattice",
            leds=_leds(8),
            buttons=[],
            switches=_switches(4),
            seven_seg=_seg(4),
        ),
        BoardDef(
            name="Gamma",
            class_name="GammaPlatform",
            vendor="Xilinx",
            leds=_leds(16),
            buttons=_buttons(4),
            switches=_switches(10),
        ),
        BoardDef(
            name="Delta",
            class_name="DeltaPlatform",
            vendor="Intel",
            leds=_leds(2),
            buttons=_buttons(1),
            switches=_switches(2),
        ),
        BoardDef(
            name="Epsilon",
            class_name="EpsilonPlatform",
            vendor="Lattice",
            leds=[],
            buttons=_buttons(3),
            switches=_switches(6),
            seven_seg=_seg(6),
        ),
        BoardDef(
            name="Zeta",
            class_name="ZetaPlatform",
            vendor="Xilinx",
            leds=_leds(6),
            buttons=_buttons(2),
            switches=_switches(4),
            seven_seg=_seg(2),
        ),
        BoardDef(
            name="Eta",
            class_name="EtaPlatform",
            vendor="Gowin",
            leds=_leds(3),
            buttons=_buttons(1),
            switches=_switches(1),
        ),
    ]


# ── Component filtering ──────────────────────────────────────────────────────


class TestComponentFiltering:
    def test_no_filters_returns_all(self, screen, boards):
        sel = BoardSelector(boards, screen)
        assert len(sel._filtered()) == 7

    def test_has_leds(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_component_filters=["has_leds"])
        names = {b.name for b in sel._filtered()}
        assert "Epsilon" not in names
        assert len(names) == 6

    def test_has_switches(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_component_filters=["has_switches"])
        names = {b.name for b in sel._filtered()}
        assert "Alpha" not in names
        assert len(names) == 6

    def test_has_buttons(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_component_filters=["has_buttons"])
        names = {b.name for b in sel._filtered()}
        assert "Beta" not in names
        assert len(names) == 6

    def test_has_7seg(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_component_filters=["has_7seg"])
        names = {b.name for b in sel._filtered()}
        assert names == {"Beta", "Epsilon", "Zeta"}

    def test_filters_compose_with_and(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_component_filters=["has_leds", "has_7seg"])
        names = {b.name for b in sel._filtered()}
        assert names == {"Beta", "Zeta"}

    def test_all_filters_narrow_maximally(self, screen, boards):
        sel = BoardSelector(
            boards,
            screen,
            initial_component_filters=[
                "has_leds",
                "has_switches",
                "has_buttons",
                "has_7seg",
            ],
        )
        names = {b.name for b in sel._filtered()}
        assert names == {"Zeta"}


# ── Vendor filtering ─────────────────────────────────────────────────────────


class TestVendorFiltering:
    def test_single_vendor(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_vendor_filters=["Xilinx"])
        names = {b.name for b in sel._filtered()}
        assert names == {"Alpha", "Gamma", "Zeta"}

    def test_multiple_vendors_compose_with_or(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_vendor_filters=["Xilinx", "Intel"])
        names = {b.name for b in sel._filtered()}
        assert names == {"Alpha", "Gamma", "Zeta", "Delta"}

    def test_other_matches_below_threshold_vendors(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_vendor_filters=["Other"])
        names = {b.name for b in sel._filtered()}
        assert names == {"Beta", "Delta", "Epsilon", "Eta"}

    def test_component_and_vendor_compose(self, screen, boards):
        sel = BoardSelector(
            boards,
            screen,
            initial_component_filters=["has_7seg"],
            initial_vendor_filters=["Xilinx"],
        )
        names = {b.name for b in sel._filtered()}
        assert names == {"Zeta"}

    def test_text_filter_composes_with_chips(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_vendor_filters=["Xilinx"])
        sel.filter_text = "gamma"
        names = {b.name for b in sel._filtered()}
        assert names == {"Gamma"}


# ── Sorting ──────────────────────────────────────────────────────────────────


class TestSorting:
    def test_default_preserves_input_order(self, screen, boards):
        sel = BoardSelector(boards, screen)
        names = [b.name for b in sel._filtered()]
        assert names == [b.name for b in boards]

    def test_sort_leds(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_sort="leds")
        names = [b.name for b in sel._filtered()]
        assert names[0] == "Gamma"
        assert names[-1] == "Epsilon"

    def test_sort_switches(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_sort="switches")
        names = [b.name for b in sel._filtered()]
        assert names[0] == "Gamma"
        assert names[-1] == "Alpha"

    def test_sort_buttons(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_sort="buttons")
        names = [b.name for b in sel._filtered()]
        assert names[0] == "Gamma"
        assert names[-1] == "Beta"

    def test_sort_7seg(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_sort="7seg")
        names = [b.name for b in sel._filtered()]
        assert names[0] == "Epsilon"
        assert names[1] == "Beta"
        assert names[2] == "Zeta"

    def test_sort_vendor(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_sort="vendor")
        vendors = [b.vendor for b in sel._filtered()]
        assert vendors == [
            "Gowin",
            "Intel",
            "Lattice",
            "Lattice",
            "Xilinx",
            "Xilinx",
            "Xilinx",
        ]

    def test_sort_total(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_sort="total")
        names = [b.name for b in sel._filtered()]
        assert names[0] == "Gamma"

    def test_sort_applies_after_filters(self, screen, boards):
        sel = BoardSelector(
            boards,
            screen,
            initial_sort="leds",
            initial_vendor_filters=["Xilinx"],
        )
        names = [b.name for b in sel._filtered()]
        assert names == ["Gamma", "Zeta", "Alpha"]


# ── Selector state ───────────────────────────────────────────────────────────


class TestSelectorState:
    def test_initial_sort_valid(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_sort="leds")
        assert sel.sort_key == "leds"

    def test_initial_sort_invalid_falls_back(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_sort="bogus")
        assert sel.sort_key == "name"

    def test_initial_sort_empty_falls_back(self, screen, boards):
        sel = BoardSelector(boards, screen)
        assert sel.sort_key == "name"

    def test_component_filters_property_sorted(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_component_filters=["has_7seg", "has_leds"])
        assert sel.component_filters == ["has_7seg", "has_leds"]

    def test_vendor_filters_property_sorted(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_vendor_filters=["Xilinx", "Intel"])
        assert sel.vendor_filters == ["Intel", "Xilinx"]

    def test_invalid_filter_key_harmless(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_component_filters=["bogus"])
        assert len(sel._filtered()) == 7

    def test_vendor_chips_above_threshold(self, screen, boards):
        sel = BoardSelector(boards, screen)
        assert "Xilinx" in sel._vendors
        assert "Lattice" not in sel._vendors
        assert sel._has_other is True

    def test_has_active_filters_false_by_default(self, screen, boards):
        sel = BoardSelector(boards, screen)
        assert not sel._has_active_filters

    def test_has_active_filters_with_text(self, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.filter_text = "x"
        assert sel._has_active_filters

    def test_has_active_filters_with_component(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_component_filters=["has_leds"])
        assert sel._has_active_filters

    def test_has_active_filters_with_vendor(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_vendor_filters=["Xilinx"])
        assert sel._has_active_filters


# ── Preselect with filters ───────────────────────────────────────────────────


class TestPreselectWithFilters:
    def test_indexes_filtered_list(self, screen, boards):
        sel = BoardSelector(
            boards,
            screen,
            preselect_class="ZetaPlatform",
            initial_component_filters=["has_7seg"],
            initial_vendor_filters=["Xilinx"],
        )
        assert len(sel._filtered()) == 1
        assert sel.hovered == 0
        assert sel.scroll == 0

    def test_preselect_without_filters(self, screen, boards):
        sel = BoardSelector(boards, screen, preselect_class="DeltaPlatform")
        assert sel.hovered == 3

    def test_preselect_not_in_filtered_list(self, screen, boards):
        sel = BoardSelector(
            boards,
            screen,
            preselect_class="AlphaPlatform",
            initial_component_filters=["has_7seg"],
        )
        assert sel.hovered == -1
        assert sel.scroll == 0


# ── Scroll clamping ──────────────────────────────────────────────────────────


class TestScrollClamping:
    def test_oversized_scroll_clamped(self, screen, boards):
        sel = BoardSelector(boards, screen, initial_component_filters=["has_7seg"])
        sel.scroll = 99999
        sel._draw()
        assert sel.scroll == 0

    def test_empty_result_clamps_to_zero(self, screen, boards):
        sel = BoardSelector(
            boards,
            screen,
            initial_component_filters=["has_7seg"],
            initial_vendor_filters=["Intel"],
        )
        sel.scroll = 500
        sel._draw()
        assert sel.scroll == 0


# ── Keyboard navigation ──────────────────────────────────────────────────────


def _key(pygame: ModuleType, key: int, unicode: str = "") -> Event:
    """Build a synthetic KEYDOWN event."""
    ev: Event = pygame.event.Event(pygame.KEYDOWN, key=key, unicode=unicode)
    return ev


class TestKeyboardNav:
    def test_down_from_unset_selects_first(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.hovered = -1
        exit_loop, result = sel._handle_keydown(_key(headless_pygame, headless_pygame.K_DOWN))
        assert exit_loop is False
        assert result is None
        assert sel.hovered == 0

    def test_up_from_unset_selects_last(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.hovered = -1
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_UP))
        assert sel.hovered == len(boards) - 1

    def test_down_advances_then_clamps_at_end(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.hovered = 0
        for _ in range(50):
            sel._handle_keydown(_key(headless_pygame, headless_pygame.K_DOWN))
        assert sel.hovered == len(boards) - 1

    def test_up_clamps_at_zero(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.hovered = 2
        for _ in range(10):
            sel._handle_keydown(_key(headless_pygame, headless_pygame.K_UP))
        assert sel.hovered == 0

    def test_enter_returns_hovered_board(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.hovered = 2
        exit_loop, result = sel._handle_keydown(_key(headless_pygame, headless_pygame.K_RETURN))
        assert exit_loop is True
        assert result is sel._filtered()[2]

    def test_kp_enter_also_selects(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.hovered = 1
        exit_loop, result = sel._handle_keydown(_key(headless_pygame, headless_pygame.K_KP_ENTER))
        assert exit_loop is True
        assert result is sel._filtered()[1]

    def test_enter_with_no_selection_continues(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.hovered = -1
        exit_loop, result = sel._handle_keydown(_key(headless_pygame, headless_pygame.K_RETURN))
        assert exit_loop is False
        assert result is None

    def test_escape_quits(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        exit_loop, result = sel._handle_keydown(_key(headless_pygame, headless_pygame.K_ESCAPE))
        assert exit_loop is True
        assert result is None

    def test_nav_indexes_filtered_list(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen, initial_component_filters=["has_7seg"])
        assert len(sel._filtered()) == 3
        sel.hovered = -1
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_UP))  # last of filtered
        assert sel.hovered == 2
        exit_loop, result = sel._handle_keydown(_key(headless_pygame, headless_pygame.K_RETURN))
        assert exit_loop is True
        assert result is sel._filtered()[2]
        assert result.name in {"Beta", "Epsilon", "Zeta"}

    def test_typing_appends_and_resets_cursor(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.hovered = 3
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_g, unicode="g"))
        assert sel.filter_text == "g"
        assert sel.hovered == -1

    def test_backspace_edits_filter_and_resets_cursor(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.filter_text = "ab"
        sel.hovered = 2
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_BACKSPACE))
        assert sel.filter_text == "a"
        assert sel.hovered == -1

    def test_pagedown_moves_by_a_page(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.hovered = 0
        page = sel._page_rows()
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_PAGEDOWN))
        assert sel.hovered == min(page, len(boards) - 1)

    def test_nav_on_empty_list_is_safe(self, headless_pygame, screen, boards):
        sel = BoardSelector(
            boards,
            screen,
            initial_component_filters=["has_7seg"],
            initial_vendor_filters=["Intel"],
        )
        assert sel._filtered() == []
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_DOWN))
        assert sel.hovered == -1
        exit_loop, result = sel._handle_keydown(_key(headless_pygame, headless_pygame.K_RETURN))
        assert exit_loop is False
        assert result is None


class TestSortDropdownKeyboard:
    def test_arrows_drive_dropdown_not_list(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel._sort_open = True
        sel.hovered = 1
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_DOWN))
        # The list cursor is untouched; the dropdown reveals the active option.
        assert sel.hovered == 1
        assert sel._hovered_sort_item == 0  # "name" is active by default

    def test_dropdown_advances_after_reveal(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel._sort_open = True
        sel._hovered_sort_item = -1
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_DOWN))  # reveal active (0)
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_DOWN))  # -> 1
        assert sel._hovered_sort_item == 1

    def test_dropdown_wraps_at_end(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel._sort_open = True
        sel._hovered_sort_item = len(_SORT_OPTIONS) - 1
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_DOWN))
        assert sel._hovered_sort_item == 0

    def test_enter_selects_sort_and_closes_without_quitting(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel._sort_open = True
        sel._hovered_sort_item = 1  # "vendor"
        exit_loop, result = sel._handle_keydown(_key(headless_pygame, headless_pygame.K_RETURN))
        assert exit_loop is False
        assert result is None
        assert sel._sort_open is False
        assert sel.sort_key == _SORT_OPTIONS[1][0]

    def test_escape_closes_dropdown_without_quitting(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel._sort_open = True
        exit_loop, result = sel._handle_keydown(_key(headless_pygame, headless_pygame.K_ESCAPE))
        assert exit_loop is False
        assert result is None
        assert sel._sort_open is False

    def test_typing_while_open_closes_and_filters(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel._sort_open = True
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_g, unicode="g"))
        assert sel._sort_open is False
        assert sel.filter_text == "g"


class TestHelpTrigger:
    def test_f1_requests_help_without_filtering(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        exit_loop, result = sel._handle_keydown(_key(headless_pygame, headless_pygame.K_F1))
        assert (exit_loop, result) == (False, None)
        assert sel._help_requested is True
        assert sel.filter_text == ""

    def test_question_mark_requests_help_not_filter(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        # `?` is intercepted above the printable-append branch, so it must not
        # leak into the board filter.
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_SLASH, unicode="?"))
        assert sel._help_requested is True
        assert sel.filter_text == ""

    def test_question_mark_preserves_existing_filter(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.filter_text = "art"
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_SLASH, unicode="?"))
        assert sel._help_requested is True
        assert sel.filter_text == "art"

    def test_question_mark_closes_open_dropdown(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel._sort_open = True
        sel._handle_keydown(_key(headless_pygame, headless_pygame.K_SLASH, unicode="?"))
        assert sel._help_requested is True
        assert sel._sort_open is False

    def test_help_button_click_requests_help(self, screen, boards):
        sel = BoardSelector(boards, screen)
        sel._draw()  # populates self._help_rect
        assert sel._help_rect is not None
        result = sel._click(sel._help_rect.center)
        assert result is None
        assert sel._help_requested is True


class TestHelpResizeReconcile:
    """A resize while the help overlay is open must reflow the selector on close."""

    def test_sync_picks_up_resized_surface(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.scroll = 120
        # Simulate the display surface having auto-resized while help was open.
        sel.screen = headless_pygame.Surface((1400, 950))
        sel._sync_to_surface()
        assert (sel.width, sel.height) == (1400, 950)
        assert sel.scroll == 0  # reset on a real size change

    def test_sync_without_resize_preserves_scroll(self, headless_pygame, screen, boards):
        sel = BoardSelector(boards, screen)
        sel.scroll = 120
        sel._sync_to_surface()  # surface unchanged (1024x700)
        assert (sel.width, sel.height) == (1024, 700)
        assert sel.scroll == 120
