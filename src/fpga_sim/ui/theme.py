"""Semantic color roles for the UI — the single source of truth for the palette.

``constants.py`` holds the raw neutral *palette* (``WHITE`` / ``BLACK`` / ``GRAY`` …);
this module holds the *semantic roles* the renderer actually reads. Every role is a
field on the frozen :class:`Theme` dataclass, and :data:`THEME` is the one default
instance (today's "pcb-green" look).

Routing every call site through ``THEME`` means swapping this object's contents
restyles the whole app without touching a single draw call — which is exactly what
:func:`set_theme` does (U6). Call sites bind ``THEME`` once at import, so the swap
happens *in place*: the one sanctioned mutation path copies a chosen theme's fields
onto the shared instance, while the frozen dataclass keeps rejecting accidental
single-field writes.

The split also keeps the import graph acyclic: ``theme`` imports :class:`ButtonStyle`
from ``ui.widgets.button``, which imports neutrals from ``ui.constants`` (a leaf).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from types import MappingProxyType

from fpga_sim.ui.constants import DARK_GRAY, GRAY, WHITE, YELLOW
from fpga_sim.ui.widgets.button import RGB, ButtonStyle

# Shared shades referenced by several roles below, defined once. The PCB-blue pair
# in particular was previously hand-typed in three buttons across two processes.
_PCB_BLUE: RGB = (20, 60, 110)
_PCB_BLUE_HI: RGB = (30, 80, 140)

# Selectable theme names + their Settings-dialog labels, in cycle order. The
# persisted session's ``theme`` key holds one of these names; the launcher applies
# it at startup and the Settings dialog cycles through them via set_theme().
THEME_NAMES: tuple[str, ...] = ("pcb-green", "dark", "high-contrast")
THEME_LABELS: Mapping[str, str] = MappingProxyType(
    {"pcb-green": "PCB Green", "dark": "Dark", "high-contrast": "High Contrast"}
)

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
    """A complete color scheme: every semantic role the UI renders.

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
    spinner_arc: RGB = (150, 200, 255)  # leading dot of the analysis spinner
    spinner_track: RGB = (70, 80, 110)  # trailing/faded dots of the spinner

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
    btn_settings: ButtonStyle = ButtonStyle(  # the gear trigger; matches btn_help
        bg=(45, 50, 70), bg_hover=(70, 85, 120), border=(120, 135, 170), radius=99
    )
    btn_settings_action: ButtonStyle = ButtonStyle(  # dialog row actions (cycle/Reset/Clear)
        bg=(50, 55, 75),
        bg_hover=(65, 75, 110),
        bg_disabled=(40, 42, 55),
        fg_disabled=(120, 120, 135),
        border_disabled=(80, 80, 95),
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


# ── Alternate themes ─────────────────────────────────────────────────────────
# Each is a full Theme built from the pcb-green defaults plus overrides; roles
# not listed keep their default because they are either component colors that
# read correctly on any surface (LEDs, switches, 7-seg) or already fit the look.

# "dark": graphite PCB with slate-blue accents. The launcher screens are already
# dark, so the visible shift is the board surface and the de-greened sim panel;
# semantic colors (ok-green, warning amber, status red) are kept.
_DARK = Theme(
    # Board surface & chip
    pcb_bg=(30, 32, 36),
    chip_default=(48, 50, 56),  # lifted so the fallback package reads on graphite
    # Selector: green-tinted rows/chips → slate blue
    sel_bg=(24, 26, 32),
    sel_row_a=(34, 36, 44),
    sel_row_b=(29, 31, 38),
    sel_hover=(44, 52, 66),
    chip_active=(40, 70, 110),
    chip_hover=(52, 62, 80),
    chip_text_active=(220, 235, 255),
    dropdown_hover=(52, 60, 75),
    # Dialogs
    panel_bg=(26, 28, 34),
    header_text=(150, 180, 220),
    # Sim panel: green accents → slate
    info_green=(200, 205, 215),
    panel_label=(160, 170, 185),
    val_clk=(170, 180, 200),
    accent_bar=(36, 44, 58),
    divider=(90, 110, 140),
    speed_fill=(70, 110, 170),
    speed_normal=(140, 155, 175),
    speed_marker_hi=(110, 170, 255),
    speed_marker_mid=(140, 165, 200),
    # Picker / sim-overlay text: decorative greens → cool neutrals
    file_entry=(225, 235, 250),
    sim_info=(185, 200, 220),
    sim_hint=(120, 140, 165),
    btn_sim_clock=ButtonStyle(
        bg=(55, 65, 85),
        bg_hover=(75, 90, 115),
        border=(90, 110, 140),
        border_width=1,
        radius=3,
        fg=WHITE,
        fg_disabled=GRAY,
        border_disabled=DARK_GRAY,
        bg_disabled=(38, 44, 56),
    ),
)

# High-contrast shades shared by many roles below.
_HC_BLACK: RGB = (0, 0, 0)
_HC_WHITE: RGB = (255, 255, 255)
_HC_YELLOW: RGB = (255, 255, 0)
_HC_HOVER: RGB = (90, 90, 90)  # button/row hover fill
_HC_MUTED: RGB = (215, 215, 215)  # "dim" text kept well above 4.5:1 on black


def _hc_button(
    bg: RGB = _HC_BLACK,
    bg_hover: RGB = _HC_HOVER,
    *,
    fg: RGB = _HC_WHITE,
    border: RGB = _HC_WHITE,
    border_width: int = 2,
    radius: int = 6,
) -> ButtonStyle:
    """Build a high-contrast ButtonStyle: black fill, white border, gray hover."""
    return ButtonStyle(
        bg=bg,
        bg_hover=bg_hover,
        fg=fg,
        border=border,
        border_width=border_width,
        radius=radius,
        bg_disabled=(30, 30, 30),
        fg_disabled=(150, 150, 150),
        border_disabled=(150, 150, 150),
    )


# "high-contrast": pure black surfaces, white text and borders, yellow accents,
# black-on-yellow for active/selected states. Every role is overridden except
# the handful whose defaults already sit at the extremes.
_HIGH_CONTRAST = Theme(
    # Board surface & components: saturated primaries on black
    pcb_bg=_HC_BLACK,
    led_on=(255, 0, 0),
    led_off=(64, 64, 64),
    switch_on=(0, 170, 255),
    switch_off=(70, 70, 70),
    push_on=_HC_YELLOW,
    push_off=(160, 160, 160),
    seg_on=_HC_YELLOW,
    seg_off=(60, 60, 60),
    seg_bg=_HC_BLACK,
    seg_bezel=(220, 220, 220),  # near-white bezel outlines each digit on black
    seg_digit_label=_HC_WHITE,
    # Chip: the default dark vendor fills stay (white/green labels need the
    # dark backing); only the labels and pins brighten.
    chip_default=(20, 20, 20),
    chip_device=_HC_WHITE,
    chip_package=(230, 230, 230),
    chip_clock=(0, 255, 0),
    chip_pin=(230, 230, 230),
    # Selector
    sel_bg=_HC_BLACK,
    sel_row_a=(26, 26, 26),
    sel_row_b=(10, 10, 10),
    sel_hover=(70, 70, 0),  # dark yellow row highlight
    board_name=_HC_WHITE,
    muted_text=_HC_MUTED,
    board_count=(200, 200, 200),
    board_source=(200, 200, 200),
    scrollbar_track=(70, 70, 70),
    scrollbar_thumb=_HC_WHITE,
    chip_active=_HC_YELLOW,  # black-on-yellow selected filter chip
    chip_inactive=(35, 35, 35),
    chip_hover=_HC_HOVER,
    chip_text=_HC_WHITE,
    chip_text_active=_HC_BLACK,
    sort_bg=(35, 35, 35),
    sort_hover=_HC_HOVER,
    sort_text=_HC_WHITE,
    dropdown_bg=_HC_BLACK,
    dropdown_hover=_HC_HOVER,
    dropdown_border=_HC_WHITE,
    input_bg=(25, 25, 25),
    # Dialogs
    panel_bg=_HC_BLACK,
    panel_border_info=_HC_WHITE,
    panel_border_error=(255, 90, 90),
    title_info=_HC_YELLOW,
    title_error=(255, 90, 90),
    header_text=_HC_YELLOW,
    body_text=_HC_WHITE,
    key_text=_HC_YELLOW,
    dim_text=_HC_MUTED,
    scroll_track=(70, 70, 70),
    scroll_thumb=_HC_WHITE,
    footer_hint=(220, 220, 220),
    spinner_arc=_HC_YELLOW,
    spinner_track=(100, 100, 100),
    # Sim panel: black bar, white text, yellow slider
    info_green=_HC_WHITE,
    panel_label=_HC_WHITE,
    val_clk=_HC_WHITE,
    val_rate=(0, 255, 255),
    val_fps=_HC_YELLOW,
    val_gdi=(255, 170, 0),
    accent_bar=_HC_BLACK,  # the divider line carries the panel boundary
    divider=_HC_WHITE,
    speed_fill=(120, 120, 0),
    speed_normal=_HC_WHITE,
    speed_marker_hi=(0, 255, 0),
    speed_marker_mid=_HC_WHITE,
    speed_marker_warn=(255, 140, 0),
    status_paused=(255, 90, 90),
    status_max=_HC_YELLOW,
    # Status / picker / sim-overlay text
    vhdl_ok=(0, 255, 0),
    warning=(255, 200, 0),
    dir_entry=(90, 190, 255),
    file_entry=_HC_WHITE,
    sim_info=_HC_WHITE,
    sim_hint=(220, 220, 220),
    # Buttons: uniform black/white/gray, with semantic go-green and danger-red
    btn_select_board=_hc_button(),
    btn_load_vhdl=_hc_button(),
    btn_start_sim=_hc_button(bg=(0, 80, 0), bg_hover=(0, 130, 0)),
    btn_sim_toggle_ghdl=_hc_button(),
    btn_sim_toggle_nvc=_hc_button(bg=(70, 0, 90), bg_hover=(110, 0, 140)),
    btn_help_close=_hc_button(),
    btn_help=_hc_button(radius=99),
    btn_settings=_hc_button(radius=99),
    btn_settings_action=_hc_button(),
    btn_error_retry=_hc_button(bg=(0, 80, 0), bg_hover=(0, 130, 0)),
    btn_error_back=_hc_button(bg=(100, 0, 0), bg_hover=(160, 0, 0), border=(255, 90, 90)),
    btn_sim_clock=_hc_button(border_width=1, radius=3),
    btn_sim_stop=_hc_button(
        bg=(100, 0, 0), bg_hover=(160, 0, 0), border=(255, 90, 90), border_width=1, radius=5
    ),
    btn_sim_pause=_hc_button(fg=_HC_YELLOW, border_width=1, radius=5),
    btn_sim_resume=_hc_button(
        bg=(200, 200, 0), bg_hover=(255, 255, 60), fg=_HC_BLACK, border_width=1, radius=5
    ),
)

# Pristine instances for every selectable name; set_theme() copies one of these
# onto the shared THEME. Theme() — all field defaults — is the pcb-green look.
_THEMES_BY_NAME: Mapping[str, Theme] = MappingProxyType(
    {"pcb-green": Theme(), "dark": _DARK, "high-contrast": _HIGH_CONTRAST}
)

# The single shared theme instance, default pcb-green. Every UI module reads
# colors from this object; set_theme() rewrites its fields in place so every
# importer restyles at its next draw.
THEME = Theme()

_current_theme_name: str = "pcb-green"


def current_theme_name() -> str:
    """Return the name of the theme currently applied to :data:`THEME`."""
    return _current_theme_name


def set_theme(name: str) -> None:
    """Apply the named theme by copying its palette onto the shared :data:`THEME`.

    Call sites bind ``THEME`` once at import, so the swap must happen in place:
    every field of the frozen instance is rewritten via ``object.__setattr__``
    (the same escape hatch dataclasses use in ``__init__``), which keeps
    accidental single-field writes impossible while allowing this one
    sanctioned path.  Raises :class:`ValueError` for a name not in
    :data:`THEME_NAMES`.
    """
    global _current_theme_name
    source = _THEMES_BY_NAME.get(name)
    if source is None:
        raise ValueError(f"unknown theme {name!r}; expected one of {THEME_NAMES}")
    for f in fields(Theme):
        object.__setattr__(THEME, f.name, getattr(source, f.name))
    _current_theme_name = name
