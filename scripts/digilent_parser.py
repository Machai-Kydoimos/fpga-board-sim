"""Parser for Digilent master XDC files — section-aware regex → board dicts.

Parses ``*-Master.xdc`` constraint files into board-definition dicts (JSON schema
shape), including ``port_conventions`` synthesised from the XDC port names.
Self-contained: no ``fpga_sim`` dependency.  Used by
``scripts/sync_digilent_xdc.py`` and the parser test suite.
"""

import re
from datetime import datetime, timezone
from typing import Any

from led_metadata import color_from_name

# ═══════════════════════════════════════════════════════════════════════
#  Board metadata — XDC files lack device/package info
# ═══════════════════════════════════════════════════════════════════════

_BOARD_METADATA: dict[str, dict[str, str]] = {
    "Arty-A7-100": {
        "name": "Arty A7-100",
        "device": "xc7a100t",
        "package": "csg324",
    },
    "Arty-A7-35": {
        "name": "Arty A7-35",
        "device": "xc7a35ti",
        "package": "csg324",
    },
    "Arty": {
        "name": "Arty",
        "device": "xc7a35ti",
        "package": "csg324",
    },
    "Arty-S7-25": {
        "name": "Arty S7-25",
        "device": "xc7s25",
        "package": "csga324",
    },
    "Arty-S7-50": {
        "name": "Arty S7-50",
        "device": "xc7s50",
        "package": "csga324",
    },
    "Arty-Z7-10": {
        "name": "Arty Z7-10",
        "device": "xc7z010",
        "package": "clg400",
    },
    "Arty-Z7-20": {
        "name": "Arty Z7-20",
        "device": "xc7z020",
        "package": "clg400",
    },
    "Basys-3": {
        "name": "Basys 3",
        "device": "xc7a35t",
        "package": "cpg236",
    },
    "Cmod-A7": {
        "name": "Cmod A7",
        "device": "xc7a35t",
        "package": "cpg236",
    },
    "Cmod-S7-25": {
        "name": "Cmod S7-25",
        "device": "xc7s25",
        "package": "csga225",
    },
    "Cora-Z7-07S": {
        "name": "Cora Z7-07S",
        "device": "xc7z007s",
        "package": "clg400",
    },
    "Cora-Z7-10": {
        "name": "Cora Z7-10",
        "device": "xc7z010",
        "package": "clg400",
    },
    "Eclypse-Z7": {
        "name": "Eclypse Z7",
        "device": "xc7z020",
        "package": "clg484",
    },
    "Genesys-2": {
        "name": "Genesys 2",
        "device": "xc7k325t",
        "package": "ffg900",
    },
    "Genesys-ZU-3EG": {
        "name": "Genesys ZU-3EG",
        "device": "xczu3eg",
        "package": "sfvc784",
    },
    "Genesys-ZU-3EG-D": {
        "name": "Genesys ZU-3EG-D",
        "device": "xczu3eg",
        "package": "sfvc784",
    },
    "Genesys-ZU-5EV-D": {
        "name": "Genesys ZU-5EV-D",
        "device": "xczu5ev",
        "package": "sfvc784",
    },
    "Nexys-4": {
        "name": "Nexys 4",
        "device": "xc7a100t",
        "package": "csg324",
    },
    "Nexys-4-DDR": {
        "name": "Nexys 4 DDR",
        "device": "xc7a100t",
        "package": "csg324",
    },
    "Nexys-A7-100T": {
        "name": "Nexys A7-100T",
        "device": "xc7a100t",
        "package": "csg324",
    },
    "Nexys-A7-50T": {
        "name": "Nexys A7-50T",
        "device": "xc7a50t",
        "package": "csg324",
    },
    "Nexys-Video": {
        "name": "Nexys Video",
        "device": "xc7a200t",
        "package": "sbg484",
    },
    "Sword": {
        "name": "Sword",
        "device": "xc7a100t",
        "package": "csg324",
    },
    "USB104-A7-100T": {
        "name": "USB104 A7-100T",
        "device": "xc7a100t",
        "package": "csg324",
    },
    "Zedboard": {
        "name": "Zedboard",
        "device": "xc7z020",
        "package": "clg484",
    },
    "Zybo": {
        "name": "Zybo",
        "device": "xc7z010",
        "package": "clg400",
    },
    "Zybo-Z7": {
        "name": "Zybo Z7",
        "device": "xc7z020",
        "package": "clg400",
    },
}

# Named buttons mapping: Digilent boards use btnC/U/L/R/D instead of btn[0..4]
_NAMED_BUTTONS: dict[str, tuple[str, int]] = {
    "btnc": ("button_center", 0),
    "btnu": ("button_up", 1),
    "btnd": ("button_down", 2),
    "btnl": ("button_left", 3),
    "btnr": ("button_right", 4),
}


# ═══════════════════════════════════════════════════════════════════════
#  XDC parsing
# ═══════════════════════════════════════════════════════════════════════

_RE_SECTION = re.compile(r"^#{2,}\s*(.+?)\s*$")

# -dict format: set_property -dict { PACKAGE_PIN X IOSTANDARD Y } [get_ports {port}]
_RE_SET_PROP_BRACES = re.compile(r"set_property\s+-dict\s*\{([^}]+)\}\s*\[get_ports\s+\{([^}]+)\}")
# -dict format without braces on port: [get_ports port]
_RE_SET_PROP_BARE = re.compile(r"set_property\s+-dict\s*\{([^}]+)\}\s*\[get_ports\s+(\w+)\s*\]")
# Separate-line PACKAGE_PIN: set_property PACKAGE_PIN X [get_ports {port}]
_RE_PKG_PIN_BRACES = re.compile(r"set_property\s+PACKAGE_PIN\s+(\w+)\s*\[get_ports\s+\{([^}]+)\}")
_RE_PKG_PIN_BARE = re.compile(r"set_property\s+PACKAGE_PIN\s+(\w+)\s*\[get_ports\s+(\w+)\s*\]")
# Separate-line IOSTANDARD: set_property IOSTANDARD X [get_ports {port}]
_RE_IOS_BRACES = re.compile(r"set_property\s+IOSTANDARD\s+(\w+)\s*\[get_ports\s+\{([^}]+)\}")
_RE_IOS_BARE = re.compile(r"set_property\s+IOSTANDARD\s+(\w+)\s*\[get_ports\s+(\w+)\s*\]")

_RE_PACKAGE_PIN = re.compile(r"PACKAGE_PIN\s+(\w+)")
_RE_IOSTANDARD = re.compile(r"IOSTANDARD\s+(\w+)")

_RE_CLOCK_PERIOD = re.compile(r"create_clock\s+.*-period\s+([\d.]+)")

_RE_INDEXED_PORT = re.compile(r"^(\w+)\[(\d+)\]$")

# A clock section names a "clock" with a frequency / "system" / "signal"
# qualifier, but not a transceiver or mezzanine reference clock (an FMC card's
# GTP/MGT clock belongs to the mezzanine, not the FPGA fabric).
_RE_CLOCK_FREQ = re.compile(r"\d+\s*m?hz")
_RE_CLOCK_NONFABRIC = re.compile(r"transceiver|mezzanine|refclk|\bmgt\b")
# An LED section names "led"/"leds" as a whole word, so "OLED Display" and
# schematic-name headers ("Sch name = LED16_G") don't masquerade as one.
_RE_LED_WORD = re.compile(r"\bleds?\b")


def _classify_section(header: str) -> str | None:
    """Map an XDC section header to a resource type.

    Digilent's section titles are inconsistent between boards, so the clock and
    LED headers are matched fuzzily but guarded:

    * A *clock* section names a "clock" together with a frequency
      (``100MHz Clock``), the word ``system`` (``PL System Clock``), or
      ``signal`` (``Clock signal``), and is not a transceiver/mezzanine
      reference clock. Requiring a qualifier rejects prose mentions such as
      ``Note: QSPI clock can only be accessed ...`` and ``GTH reference clock
      jitter filter ...`` (their frequency, when they carry one, still reaches
      ``default_clock_hz`` via the section-agnostic ``create_clock`` regex). The
      transceiver/mezzanine exclusion rejects an FMC card's clock
      (``FMC Transceiver clocks ... 156.25 MHz``), which is the mezzanine's, not
      the FPGA fabric's; a genuine fabric clock that merely *sources* from a
      peripheral (``125MHz Clock from Ethernet PHY``, whose port is the
      ``sysclk``) is still matched.
    * An *LED* section names ``led``/``leds`` as a whole word (``LEDs``,
      ``4 LEDs``), checked after the RGB rule so ``RGB LEDs`` routes to
      ``rgb_led``; the word boundary keeps ``OLED Display`` and
      ``Sch name = LED16_G`` out.
    """
    h = header.lower().strip()
    if (
        "clock" in h
        and (_RE_CLOCK_FREQ.search(h) or "system" in h or "signal" in h)
        and not _RE_CLOCK_NONFABRIC.search(h)
    ):
        return "clock"
    if "switch" in h:
        return "switch"
    if "rgb" in h and "led" in h:
        return "rgb_led"
    if _RE_LED_WORD.search(h):
        return "led"
    if "button" in h:
        return "button"
    if "7 segment" in h or "7segment" in h or "seven seg" in h:
        return "seven_seg"
    return None


def _parse_port_name(port: str) -> tuple[str, int | None]:
    """Parse 'led[0]' → ('led', 0) or 'btnC' → ('btnC', None)."""
    m = _RE_INDEXED_PORT.match(port.strip())
    if m:
        return m.group(1), int(m.group(2))
    return port.strip(), None


def parse_xdc(content: str) -> dict[str, Any]:
    """Parse an XDC file into structured pin data grouped by section type."""
    pins: dict[str, list[dict[str, Any]]] = {}
    clock_period_ns: float | None = None
    current_type: str | None = None
    port_iostandard: dict[str, str] = {}

    for line in content.split("\n"):
        sec_match = _RE_SECTION.match(line)
        if sec_match:
            header = sec_match.group(1)
            classified = _classify_section(header)
            if classified is not None:
                current_type = classified
            elif "=" not in header:
                current_type = None
            continue

        # Try -dict format (combined pin + iostandard on one line)
        prop_match = _RE_SET_PROP_BRACES.search(line) or _RE_SET_PROP_BARE.search(line)
        if prop_match and current_type:
            dict_content = prop_match.group(1)
            port_raw = prop_match.group(2).strip()
            pin_m = _RE_PACKAGE_PIN.search(dict_content)
            ios_m = _RE_IOSTANDARD.search(dict_content)
            if pin_m:
                entry = {
                    "pin": pin_m.group(1),
                    "iostandard": ios_m.group(1) if ios_m else "",
                    "port": port_raw,
                }
                pins.setdefault(current_type, []).append(entry)
            continue

        # Try separate-line PACKAGE_PIN format
        pkg_match = _RE_PKG_PIN_BRACES.search(line) or _RE_PKG_PIN_BARE.search(line)
        if pkg_match and current_type:
            pin = pkg_match.group(1)
            port_raw = pkg_match.group(2).strip()
            entry = {
                "pin": pin,
                "iostandard": port_iostandard.get(port_raw, ""),
                "port": port_raw,
            }
            pins.setdefault(current_type, []).append(entry)
            continue

        # Try separate-line IOSTANDARD format
        ios_match = _RE_IOS_BRACES.search(line) or _RE_IOS_BARE.search(line)
        if ios_match:
            ios_name = ios_match.group(1)
            port_raw = ios_match.group(2).strip()
            port_iostandard[port_raw] = ios_name
            for section_entries in pins.values():
                for entry in section_entries:
                    if entry["port"] == port_raw and not entry["iostandard"]:
                        entry["iostandard"] = ios_name
            continue

        clk_match = _RE_CLOCK_PERIOD.search(line)
        if clk_match:
            clock_period_ns = float(clk_match.group(1))

    return {"pins": pins, "clock_period_ns": clock_period_ns}


# ═══════════════════════════════════════════════════════════════════════
#  Component building
# ═══════════════════════════════════════════════════════════════════════


def _build_led_components(pin_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build LED component dicts from parsed XDC pin entries."""
    components: list[dict[str, Any]] = []
    for entry in pin_entries:
        base, idx = _parse_port_name(entry["port"])
        if idx is None:
            idx = len(components)
        comp: dict[str, Any] = {
            "name": "led",
            "number": idx,
            "pins": [entry["pin"]],
            "direction": "o",
            "inverted": False,
            "connector": None,
            "attrs": {"IOSTANDARD": entry["iostandard"]} if entry["iostandard"] else {},
        }
        # Digilent LED ports are bare `led[n]` (color comes from the registry, not
        # the name), but honor the shared heuristic so a future color-named XDC
        # port still populates `color` (U36). No-op on today's data.
        color = color_from_name(base)
        if color:
            comp["color"] = color
        components.append(comp)
    return sorted(components, key=lambda c: c["number"])


def _build_rgb_led_components(pin_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build RGB LED component dicts, grouping r/g/b pins by LED index."""
    groups: dict[int, dict[str, str]] = {}
    iostandard = ""
    for entry in pin_entries:
        port = entry["port"].strip()
        iostandard = entry.get("iostandard", iostandard)
        # Patterns: led0_r / LED16_R / led0_b / ld0_r
        m = re.match(r"(?:led|LED|ld|LD)(\d+)[_]?([rgb]|[RGB])", port, re.IGNORECASE)
        if m:
            led_idx = int(m.group(1))
            color = m.group(2).lower()
            groups.setdefault(led_idx, {})[color] = entry["pin"]

    components: list[dict[str, Any]] = []
    for idx in sorted(groups):
        g = groups[idx]
        pins = [g.get("r", ""), g.get("g", ""), g.get("b", "")]
        pins = [p for p in pins if p]
        components.append(
            {
                "name": "rgb_led",
                "number": idx,
                "pins": pins,
                "direction": "o",
                "inverted": False,
                "connector": None,
                "attrs": {"IOSTANDARD": iostandard} if iostandard else {},
            }
        )
    return components


def _build_switch_components(pin_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build switch component dicts from parsed XDC pin entries."""
    components: list[dict[str, Any]] = []
    for entry in pin_entries:
        base, idx = _parse_port_name(entry["port"])
        if idx is None:
            idx = len(components)
        components.append(
            {
                "name": "switch",
                "number": idx,
                "pins": [entry["pin"]],
                "direction": "i",
                "inverted": False,
                "connector": None,
                "attrs": {"IOSTANDARD": entry["iostandard"]} if entry["iostandard"] else {},
            }
        )
    return sorted(components, key=lambda c: c["number"])


def _build_button_components(pin_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build button component dicts. Handles both indexed and named buttons."""
    components: list[dict[str, Any]] = []
    for entry in pin_entries:
        base, idx = _parse_port_name(entry["port"])
        port_lower = entry["port"].strip().lower()

        if idx is not None:
            name = "button"
            number = idx
        elif port_lower in _NAMED_BUTTONS:
            name, number = _NAMED_BUTTONS[port_lower]
        else:
            name = "button"
            number = len(components)

        components.append(
            {
                "name": name,
                "number": number,
                "pins": [entry["pin"]],
                "direction": "i",
                "inverted": False,
                "connector": None,
                "attrs": {"IOSTANDARD": entry["iostandard"]} if entry["iostandard"] else {},
            }
        )
    return sorted(components, key=lambda c: c["number"])


def _build_seven_seg(pin_entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Build seven_seg definition from parsed 7-segment XDC section."""
    if not pin_entries:
        return None

    segments: list[str] = []
    anodes: list[str] = []
    has_dp = False

    for entry in pin_entries:
        port = entry["port"].strip()
        port_lower = port.lower()

        # Detect anode/digit-select pins
        base, idx = _parse_port_name(port)
        if base.lower() in ("an",):
            anodes.append(port)
            continue

        # Detect decimal point
        if port_lower in ("dp",):
            has_dp = True
            continue

        # Detect indexed segments: seg[0]..seg[6]
        if base.lower() in ("seg",) and idx is not None:
            segments.append(port)
            continue

        # Detect individual segments: CA, CB, CC, CD, CE, CF, CG
        if port_lower in ("ca", "cb", "cc", "cd", "ce", "cf", "cg"):
            segments.append(port)
            continue

    if not segments:
        return None

    num_digits = max(len(anodes), 1)
    return {
        "num_digits": num_digits,
        "has_dp": has_dp,
        "is_multiplexed": len(anodes) > 0,
        "inverted": True,
        "select_inverted": True,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Port conventions
# ═══════════════════════════════════════════════════════════════════════


def _build_port_conventions(parsed: dict[str, Any], board_key: str) -> dict[str, dict[str, Any]]:
    """Build port_conventions from parsed XDC data."""
    pins = parsed["pins"]
    convention: dict[str, object] = {
        "description": f"Digilent {board_key} Master XDC port names",
    }

    # Clock port name
    clock_entries = pins.get("clock", [])
    if clock_entries:
        port = clock_entries[0]["port"].strip()
        convention["clk"] = port

    # LEDs
    led_entries = pins.get("led", [])
    if led_entries:
        first_port = led_entries[0]["port"].strip()
        base, _ = _parse_port_name(first_port)
        convention["leds"] = {"name": base, "width": len(led_entries)}

    # Switches
    sw_entries = pins.get("switch", [])
    if sw_entries:
        first_port = sw_entries[0]["port"].strip()
        base, _ = _parse_port_name(first_port)
        convention["switches"] = {"name": base, "width": len(sw_entries)}

    # Buttons — only if indexed (not named)
    btn_entries = pins.get("button", [])
    if btn_entries:
        first_port = btn_entries[0]["port"].strip()
        base, idx = _parse_port_name(first_port)
        if idx is not None:
            convention["buttons"] = {
                "name": base,
                "width": len(btn_entries),
                "active_low": False,
            }
        else:
            convention["buttons"] = {
                "name": first_port.rstrip("CUDLRcudlr"),
                "width": len(btn_entries),
                "active_low": False,
            }

    # 7-segment
    seg_entries = pins.get("seven_seg", [])
    if seg_entries:
        segments: list[str] = []
        for entry in seg_entries:
            port = entry["port"].strip()
            port_lower = port.lower()
            if port_lower not in ("dp",) and not port.lower().startswith("an"):
                base, idx = _parse_port_name(port)
                if base.lower() not in ("an",):
                    segments.append(port)

        if segments:
            first_seg = segments[0]
            base, idx = _parse_port_name(first_seg)
            if idx is not None:
                convention["seven_seg"] = {
                    "style": "packed_vector",
                    "name": base,
                    "width_per_digit": 7,
                    "active_low": True,
                }
            else:
                convention["seven_seg"] = {
                    "style": "individual",
                    "names": segments[:7],
                    "width_per_digit": 7,
                    "active_low": True,
                }

    if len(convention) <= 1:
        return {}
    return {"digilent": convention}


# ═══════════════════════════════════════════════════════════════════════
#  Board JSON generation
# ═══════════════════════════════════════════════════════════════════════


def build_board_json(
    xdc_content: str,
    xdc_filename: str,
    commit_sha: str,
    schema_ref: str = "../schema/board.schema.json",
) -> dict[str, Any] | None:
    """Parse one XDC file and return a complete board JSON dict."""
    board_key = xdc_filename.replace("-Master.xdc", "")
    meta = _BOARD_METADATA.get(board_key, {})

    parsed = parse_xdc(xdc_content)
    pins = parsed["pins"]

    if not any(pins.get(t) for t in ("led", "switch", "button", "rgb_led")):
        return None

    board_name = meta.get("name", board_key.replace("-", " "))
    class_name = re.sub(r"[^a-zA-Z0-9]", "", board_key) + "Platform"

    # Clock
    clock_hz: float | None = None
    clock_entries = pins.get("clock", [])
    if parsed["clock_period_ns"] and parsed["clock_period_ns"] > 0:
        clock_hz = 1e9 / parsed["clock_period_ns"]

    clocks: list[dict[str, Any]] = []
    if clock_entries and clock_hz:
        clocks.append(
            {
                "name": clock_entries[0]["port"].strip(),
                "hz": clock_hz,
                "pin": clock_entries[0]["pin"],
                "is_default": True,
            }
        )

    # Components
    leds = _build_led_components(pins.get("led", []))
    rgb_leds = _build_rgb_led_components(pins.get("rgb_led", []))
    switches = _build_switch_components(pins.get("switch", []))
    buttons = _build_button_components(pins.get("button", []))
    seven_seg = _build_seven_seg(pins.get("seven_seg", []))

    timestamp = datetime.now(timezone.utc).isoformat()

    board: dict[str, Any] = {
        "$schema": schema_ref,
        "name": board_name,
        "class_name": class_name,
        "vendor": "Xilinx",
        "device": meta.get("device", ""),
        "package": meta.get("package", ""),
        "clocks": clocks,
        "default_clock_hz": clock_hz or 100e6,
        "leds": leds + rgb_leds,
        "buttons": buttons,
        "switches": switches,
        "seven_seg": seven_seg,
        "source": {
            "origin": "digilent-xdc",
            "upstream_file": xdc_filename,
            "sync_commit": commit_sha,
            "sync_timestamp": timestamp,
        },
    }

    port_conv = _build_port_conventions(parsed, board_key)
    if port_conv:
        board["port_conventions"] = port_conv

    return board
