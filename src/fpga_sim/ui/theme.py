"""Semantic colour roles for the UI — the single source of truth for the palette.

``constants.py`` holds the raw neutral *palette* (``WHITE`` / ``BLACK`` / ``GRAY`` …);
this module holds the *semantic roles* the renderer actually reads. Every role is a
field on the frozen :class:`Theme` dataclass, and :data:`THEME` is the one default
instance (today's "pcb-green" look).

Routing every call site through ``THEME`` means a future theme system can swap this
object's contents to restyle the whole app without touching a single draw call. For
now there is exactly one theme; nothing user-facing changes.

The split also keeps the import graph acyclic: ``theme`` imports :class:`ButtonStyle`
from ``ui.widgets.button``, which imports neutrals from ``ui.constants`` (a leaf).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from fpga_sim.ui.constants import DARK_GRAY, GRAY, WHITE, YELLOW
from fpga_sim.ui.widgets.button import RGB, ButtonStyle

# Shared shades referenced by several roles below, defined once. The PCB-blue pair
# in particular was previously hand-typed in three buttons across two processes.
_PCB_BLUE: RGB = (20, 60, 110)
_PCB_BLUE_HI: RGB = (30, 80, 140)

# FPGA vendor → package fill. Immutable so every Theme can safely share one instance.
_VENDOR_COLORS: Mapping[str, RGB] = MappingProxyType(
    {
        "Xilinx": (20, 60, 140),
        "Intel": (0, 90, 50),
        "Lattice": (90, 20, 90),
        "QuickLogic": (130, 60, 0),
        "Gowin": (70, 70, 0),
    }
)


@dataclass(frozen=True)
class Theme:
    """A complete colour scheme: every semantic role the UI renders.

    The field defaults define the "pcb-green" theme. A future theme system can
    construct alternate instances; call sites only ever read the module-level
    :data:`THEME`, so swapping the scheme touches no draw code.
    """

    # ── Board surface & components ──────────────────────────────────────────
    pcb_bg: RGB = (34, 139, 34)
    led_on: RGB = (255, 30, 30)
    led_off: RGB = (80, 0, 0)
    switch_on: RGB = (80, 140, 255)
    switch_off: RGB = (40, 50, 80)
    push_on: RGB = YELLOW  # pressed push-button
    push_off: RGB = GRAY  # idle push-button body

    # ── 7-segment display ───────────────────────────────────────────────────
    seg_on: RGB = (255, 140, 0)  # amber
    seg_off: RGB = (45, 25, 5)  # ghost segments
    seg_bg: RGB = (15, 15, 15)
    seg_bezel: RGB = (5, 5, 5)  # near-black digit bezel (pygame + SVG)
    seg_digit_label: RGB = (90, 90, 90)  # dim per-digit index label (pygame + SVG)

    # ── FPGA chip package ───────────────────────────────────────────────────
    chip_default: RGB = (40, 40, 40)  # vendor fallback fill
    chip_device: RGB = (200, 200, 200)
    chip_package: RGB = (150, 150, 150)
    chip_clock: RGB = (120, 200, 120)
    chip_pin: RGB = (120, 120, 120)
    vendor_colors: Mapping[str, RGB] = field(default_factory=lambda: _VENDOR_COLORS)

    # ── Selector screen ─────────────────────────────────────────────────────
    sel_bg: RGB = (30, 30, 40)
    sel_row_a: RGB = (40, 40, 50)
    sel_row_b: RGB = (35, 35, 45)
    sel_hover: RGB = (50, 70, 50)
    board_name: RGB = (220, 220, 255)
    muted_text: RGB = (150, 150, 150)  # board summary line, picker path
    board_count: RGB = (120, 120, 120)
    board_source: RGB = (120, 120, 120)  # dim per-row source tag (litex/amaranth/…)
    scrollbar_track: RGB = (62, 62, 76)
    scrollbar_thumb: RGB = (140, 140, 165)
    chip_active: RGB = (45, 110, 55)
    chip_inactive: RGB = (50, 50, 60)
    chip_hover: RGB = (60, 75, 65)
    chip_text: RGB = (200, 200, 210)
    chip_text_active: RGB = (230, 255, 230)
    sort_bg: RGB = (50, 55, 75)
    sort_hover: RGB = (65, 70, 90)
    sort_text: RGB = (180, 190, 220)
    dropdown_bg: RGB = (42, 42, 55)
    dropdown_hover: RGB = (55, 65, 55)
    dropdown_border: RGB = (70, 70, 85)
    input_bg: RGB = (50, 50, 60)  # filter/search box background

    # ── Dialogs (help / error) ──────────────────────────────────────────────
    panel_bg: RGB = (30, 30, 40)
    panel_border_info: RGB = (90, 130, 200)
    panel_border_error: RGB = (200, 60, 60)
    title_info: RGB = (150, 200, 255)
    title_error: RGB = (255, 100, 100)
    header_text: RGB = (140, 205, 150)
    body_text: RGB = (220, 220, 220)
    key_text: RGB = (255, 225, 120)
    dim_text: RGB = (150, 150, 160)
    scroll_track: RGB = (80, 80, 100)
    scroll_thumb: RGB = (160, 160, 200)
    footer_hint: RGB = (140, 140, 140)

    # ── Sim panel ───────────────────────────────────────────────────────────
    info_green: RGB = (180, 220, 180)  # section headers + board summary text
    panel_label: RGB = (150, 185, 150)
    val_clk: RGB = (150, 190, 150)
    val_rate: RGB = (100, 200, 255)
    val_fps: RGB = (200, 200, 100)
    val_gdi: RGB = (180, 150, 100)
    accent_bar: RGB = (24, 96, 24)
    divider: RGB = (80, 160, 80)
    speed_fill: RGB = (60, 160, 60)
    speed_normal: RGB = (130, 170, 130)
    speed_marker_hi: RGB = (100, 240, 120)
    speed_marker_mid: RGB = (140, 200, 140)
    speed_marker_warn: RGB = (255, 180, 80)
    status_paused: RGB = (255, 100, 100)
    status_max: RGB = (255, 210, 80)

    # ── Status / picker / sim-overlay text ──────────────────────────────────
    vhdl_ok: RGB = (140, 220, 140)
    warning: RGB = (210, 170, 70)
    dir_entry: RGB = (180, 180, 255)
    file_entry: RGB = (220, 255, 220)
    sim_info: RGB = (170, 210, 170)
    sim_hint: RGB = (110, 160, 110)

    # ── Buttons (ButtonStyle composites) ────────────────────────────────────
    btn_select_board: ButtonStyle = ButtonStyle(bg=(15, 75, 90), bg_hover=(20, 100, 115))
    btn_load_vhdl: ButtonStyle = ButtonStyle(bg=_PCB_BLUE, bg_hover=_PCB_BLUE_HI)
    btn_start_sim: ButtonStyle = ButtonStyle(
        bg=(20, 90, 40),
        bg_hover=(30, 120, 60),
        bg_disabled=(30, 55, 35),
        fg_disabled=(100, 140, 105),
        border_disabled=(70, 100, 75),
    )
    btn_sim_toggle_ghdl: ButtonStyle = ButtonStyle(
        bg=_PCB_BLUE,
        bg_hover=_PCB_BLUE_HI,
        bg_disabled=(50, 50, 60),
        fg_disabled=(140, 140, 150),
        border_disabled=(100, 100, 110),
    )
    btn_sim_toggle_nvc: ButtonStyle = ButtonStyle(
        bg=(80, 30, 100),
        bg_hover=(100, 40, 130),
        bg_disabled=(80, 30, 100),
        fg_disabled=(140, 140, 150),
        border_disabled=(100, 100, 110),
    )
    btn_help_close: ButtonStyle = ButtonStyle(bg=(45, 50, 70), bg_hover=(65, 75, 110))
    btn_help: ButtonStyle = ButtonStyle(  # the (?) trigger; big radius → circular
        bg=(45, 50, 70), bg_hover=(70, 85, 120), border=(120, 135, 170), radius=99
    )
    btn_error_retry: ButtonStyle = ButtonStyle(bg=(25, 70, 25), bg_hover=(40, 110, 40))
    btn_error_back: ButtonStyle = ButtonStyle(
        bg=(55, 25, 25), bg_hover=(90, 40, 40), border=(200, 100, 100)
    )
    btn_sim_clock: ButtonStyle = ButtonStyle(
        bg=(55, 80, 55),
        bg_hover=(75, 105, 75),
        border=(90, 130, 90),
        border_width=1,
        radius=3,
        fg=WHITE,
        fg_disabled=GRAY,
        border_disabled=DARK_GRAY,
        bg_disabled=(38, 50, 38),
    )
    btn_sim_stop: ButtonStyle = ButtonStyle(
        bg=(110, 28, 28),
        bg_hover=(160, 40, 40),
        fg=(240, 100, 100),
        border=(220, 90, 90),
        border_width=1,
        radius=5,
    )
    btn_sim_pause: ButtonStyle = ButtonStyle(
        bg=_PCB_BLUE,
        bg_hover=_PCB_BLUE_HI,
        fg=(255, 220, 80),
        border=(80, 140, 220),
        border_width=1,
        radius=5,
    )
    btn_sim_resume: ButtonStyle = ButtonStyle(
        bg=(100, 80, 20),
        bg_hover=(130, 110, 30),
        fg=(255, 220, 80),
        border=(200, 180, 80),
        border_width=1,
        radius=5,
    )


# The single default theme. Every UI module reads colours from this instance.
THEME = Theme()
