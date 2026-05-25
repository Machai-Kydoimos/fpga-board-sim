"""Sync board definitions from Digilent master XDC constraint files.

Downloads the digilent-xdc GitHub repository, parses each .xdc file
using section-aware regex, and emits JSON board definitions with
port_conventions to boards/digilent-xdc/.
"""

import argparse
import io
import json
import re
import sys
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

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
_RE_SET_PROP_BRACES = re.compile(
    r"set_property\s+-dict\s*\{([^}]+)\}\s*\[get_ports\s+\{([^}]+)\}"
)
# -dict format without braces on port: [get_ports port]
_RE_SET_PROP_BARE = re.compile(
    r"set_property\s+-dict\s*\{([^}]+)\}\s*\[get_ports\s+(\w+)\s*\]"
)
# Separate-line PACKAGE_PIN: set_property PACKAGE_PIN X [get_ports {port}]
_RE_PKG_PIN_BRACES = re.compile(
    r"set_property\s+PACKAGE_PIN\s+(\w+)\s*\[get_ports\s+\{([^}]+)\}"
)
_RE_PKG_PIN_BARE = re.compile(
    r"set_property\s+PACKAGE_PIN\s+(\w+)\s*\[get_ports\s+(\w+)\s*\]"
)
# Separate-line IOSTANDARD: set_property IOSTANDARD X [get_ports {port}]
_RE_IOS_BRACES = re.compile(
    r"set_property\s+IOSTANDARD\s+(\w+)\s*\[get_ports\s+\{([^}]+)\}"
)
_RE_IOS_BARE = re.compile(
    r"set_property\s+IOSTANDARD\s+(\w+)\s*\[get_ports\s+(\w+)\s*\]"
)

_RE_PACKAGE_PIN = re.compile(r"PACKAGE_PIN\s+(\w+)")
_RE_IOSTANDARD = re.compile(r"IOSTANDARD\s+(\w+)")

_RE_CLOCK_PERIOD = re.compile(r"create_clock\s+.*-period\s+([\d.]+)")

_RE_INDEXED_PORT = re.compile(r"^(\w+)\[(\d+)\]$")


def _classify_section(header: str) -> str | None:
    """Map an XDC section header to a resource type."""
    h = header.lower().strip()
    if "clock" in h and "signal" in h:
        return "clock"
    if "switch" in h:
        return "switch"
    if "rgb" in h and "led" in h:
        return "rgb_led"
    if h == "leds" or h == "led":
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


def parse_xdc(content: str) -> dict:
    """Parse an XDC file into structured pin data grouped by section type."""
    pins: dict[str, list[dict]] = {}
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


def _build_led_components(pin_entries: list[dict]) -> list[dict]:
    """Build LED component dicts from parsed XDC pin entries."""
    components: list[dict] = []
    for entry in pin_entries:
        base, idx = _parse_port_name(entry["port"])
        if idx is None:
            idx = len(components)
        components.append(
            {
                "name": "led",
                "number": idx,
                "pins": [entry["pin"]],
                "direction": "o",
                "inverted": False,
                "connector": None,
                "attrs": {"IOSTANDARD": entry["iostandard"]} if entry["iostandard"] else {},
            }
        )
    return sorted(components, key=lambda c: c["number"])


def _build_rgb_led_components(pin_entries: list[dict]) -> list[dict]:
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

    components: list[dict] = []
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


def _build_switch_components(pin_entries: list[dict]) -> list[dict]:
    """Build switch component dicts from parsed XDC pin entries."""
    components: list[dict] = []
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


def _build_button_components(pin_entries: list[dict]) -> list[dict]:
    """Build button component dicts. Handles both indexed and named buttons."""
    components: list[dict] = []
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


def _build_seven_seg(pin_entries: list[dict]) -> dict | None:
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


def _build_port_conventions(
    parsed: dict, board_key: str
) -> dict[str, dict]:
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
) -> dict | None:
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

    clocks: list[dict] = []
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

    board: dict = {
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


# ═══════════════════════════════════════════════════════════════════════
#  Archive handling
# ═══════════════════════════════════════════════════════════════════════

_REPO = "Digilent/digilent-xdc"


def resolve_commit_sha(ref: str) -> str:
    """Resolve a git ref to a commit SHA via the GitHub API."""
    url = f"https://api.github.com/repos/{_REPO}/commits/{ref}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.sha"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return str(resp.read().decode().strip())
    except Exception:
        return ref


def download_archive(ref: str) -> bytes:
    """Download the digilent-xdc archive for the given git ref."""
    url = f"https://github.com/{_REPO}/archive/{ref}.tar.gz"
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(url, timeout=60) as resp:
        return bytes(resp.read())


def extract_xdc_files(archive_bytes: bytes) -> dict[str, str]:
    """Extract .xdc files from the tarball. Returns {filename: source}."""
    xdc_files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = Path(member.name).name
            if name.endswith(".xdc") and name.endswith("-Master.xdc"):
                f = tar.extractfile(member)
                if f is not None:
                    xdc_files[name] = f.read().decode("utf-8")
    return xdc_files


# ═══════════════════════════════════════════════════════════════════════
#  Output
# ═══════════════════════════════════════════════════════════════════════


def sanitize_filename(name: str) -> str:
    """Convert a board name to a filesystem-safe base name."""
    result: list[str] = []
    for ch in name.lower():
        result.append(ch if (ch.isalnum() or ch == "-") else "_")
    safe = "".join(result)
    while "__" in safe or "--" in safe:
        safe = safe.replace("__", "_").replace("--", "-")
    return safe.strip("_-")


def write_outputs(
    output_dir: Path,
    board_jsons: dict[str, str],
    commit_sha: str,
    dry_run: bool = False,
) -> None:
    """Write JSON files and sync metadata to the output directory."""
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in sorted(board_jsons.items()):
        out_path = output_dir / filename
        if dry_run:
            print(f"  [dry-run] Would write {out_path}")
        else:
            out_path.write_text(content, encoding="utf-8")

    metadata = {
        "source_repo": f"https://github.com/{_REPO}",
        "source_commit": commit_sha,
        "sync_timestamp": datetime.now(timezone.utc).isoformat(),
        "board_count": len(board_jsons),
        "files_written": sorted(board_jsons.keys()),
    }
    meta_path = output_dir / "_sync_metadata.json"
    if dry_run:
        print(f"  [dry-run] Would write {meta_path} ({len(board_jsons)} boards)")
    else:
        meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Sync board definitions from Digilent master XDC files."
    )
    parser.add_argument(
        "--ref",
        default="master",
        help="Git ref to sync from (branch, tag, or commit SHA). Default: master",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "boards" / "digilent-xdc",
        help="Output directory for JSON files. Default: boards/digilent-xdc/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing anything.",
    )
    args = parser.parse_args()

    print(f"Resolving ref '{args.ref}' ...")
    commit_sha = resolve_commit_sha(args.ref)
    print(f"Commit: {commit_sha}")

    try:
        archive_bytes = download_archive(args.ref)
    except Exception as e:
        print(f"Error downloading archive: {e}", file=sys.stderr)
        return 1

    print("Extracting XDC files ...")
    xdc_files = extract_xdc_files(archive_bytes)
    print(f"Found {len(xdc_files)} XDC files.")

    if not xdc_files:
        print("No XDC files found in archive.", file=sys.stderr)
        return 1

    print("Generating JSON definitions ...")
    board_jsons: dict[str, str] = {}
    for filename, content in sorted(xdc_files.items()):
        try:
            board = build_board_json(content, filename, commit_sha)
        except Exception as e:
            print(f"  [skip] {filename}: {e}", file=sys.stderr)
            continue

        if board is None:
            print(f"  [skip] {filename}: no simulatable resources")
            continue

        out_name = sanitize_filename(board["name"])
        board_jsons[f"{out_name}.json"] = json.dumps(board, indent=2) + "\n"
        seg_info = ""
        if board.get("seven_seg"):
            seg_info = f", {board['seven_seg']['num_digits']}-digit 7seg"
        conv_info = " +port_conventions" if board.get("port_conventions") else ""
        print(
            f"  {filename} -> {out_name}.json"
            f" ({len(board['leds'])} LEDs, {len(board['switches'])} SW,"
            f" {len(board['buttons'])} BTN{seg_info}{conv_info})"
        )

    print(f"Generated {len(board_jsons)} board definitions.")

    print(f"\nWriting to {args.output_dir} ...")
    write_outputs(args.output_dir, board_jsons, commit_sha, dry_run=args.dry_run)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
