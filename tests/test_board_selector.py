"""Tests for BoardSelector: faceted filtering, sorting, and scroll behaviour."""

import os

import pytest

from fpga_sim.board_loader import BoardDef, ComponentInfo, SevenSegDef
from fpga_sim.ui.board_selector import BoardSelector

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def headless_pygame():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame

    pygame.init()
    yield pygame
    pygame.quit()


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
