"""Sync board definitions from litex-boards GitHub repository.

Downloads the source archive, mocks the LiteX build system classes,
executes each board platform file, and emits JSON board definitions
to boards/litex-boards/.
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
#  Mock LiteX build system classes
# ═══════════════════════════════════════════════════════════════════════


class _Pins:
    def __init__(self, pins_str: str = "", dir: str = "io", conn: object = None,
                 assert_width: int | None = None) -> None:
        self.names = pins_str.split() if isinstance(pins_str, str) else []
        self.dir = dir
        self.conn = conn


class _IOStandard:
    def __init__(self, name: str = "") -> None:
        self.name = name


class _Subsignal:
    def __init__(self, name: str, *ios: object, **kwargs: object) -> None:
        self.name = name
        self.ios = list(ios)


class _Misc:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


class _DiffPairs:
    def __init__(self, p: str = "", n: str = "", dir: str = "io",
                 conn: object = None, assert_width: int | None = None) -> None:
        self.p = p.split() if isinstance(p, str) else list(p)
        self.n = n.split() if isinstance(n, str) else list(n)
        self.dir = dir


class _Connector:
    def __init__(self, name: str = "", number: int = 0, pins: str | dict = "",
                 **kwargs: object) -> None:
        self.name = name
        self.number = number
        if isinstance(pins, str):
            self.mapping: dict[str, str] = {}
            for i, p in enumerate(pins.split()):
                if p != "-":
                    self.mapping[str(i)] = p
        elif isinstance(pins, dict):
            self.mapping = {str(k): str(v) for k, v in pins.items()}
        else:
            self.mapping = {}


class _Inverted:
    pass


class _Drive:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


class _PlatformInfo:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Mock vendor platform base classes
# ═══════════════════════════════════════════════════════════════════════

_PLATFORM_VENDORS: dict[str, str] = {
    "GenericPlatform": "Unknown",
    "Xilinx7SeriesPlatform": "Xilinx",
    "XilinxUSPlatform": "Xilinx",
    "XilinxUSPPlatform": "Xilinx",
    "XilinxSpartan6Platform": "Xilinx",
    "XilinxPlatform": "Xilinx",
    "AlteraPlatform": "Intel",
    "IntelPlatform": "Intel",
    "LatticeECP5Platform": "Lattice",
    "LatticeICE40Platform": "Lattice",
    "LatticeMachXO2Platform": "Lattice",
    "LatticeMachXO3Platform": "Lattice",
    "LatticeMachXO3LPlatform": "Lattice",
    "LatticeCrossLinkNXPlatform": "Lattice",
    "LatticeNexusPlatform": "Lattice",
    "LatticeCertusPro_NXPlatform": "Lattice",
    "GowinPlatform": "Gowin",
    "EfinixPlatform": "Efinix",
    "CologneChipPlatform": "CologneChip",
    "AnarchiPlatform": "Anarchi",
    "OsvvmPlatform": "OSVVM",
}


def _make_mock_platform(name: str, vendor: str) -> type:
    """Create a mock platform class for a given vendor."""

    class MockPlatform:
        _vendor = vendor

        def __init__(self, device: object = "", io: object = None,
                     connectors: object = None, **kwargs: object) -> None:
            self.device = str(device) if device else ""
            self._captured_io: list[tuple] = list(io) if isinstance(io, (list, tuple)) else []

        def add_resources(self, resources: object) -> None:
            if isinstance(resources, list):
                self._captured_io.extend(resources)

        def add_connectors(self, connectors: object) -> None:
            pass

        def add_extension(self, *args: object, **kwargs: object) -> None:
            pass

        def request(self, *args: object, **kwargs: object) -> None:
            pass

    MockPlatform.__name__ = name
    MockPlatform.__qualname__ = name
    MockPlatform._vendor = vendor
    return MockPlatform


# ═══════════════════════════════════════════════════════════════════════
#  Exec namespace
# ═══════════════════════════════════════════════════════════════════════


def _make_litex_namespace() -> dict[str, object]:
    """Build the mock namespace for executing litex board files."""
    ns: dict[str, object] = {
        # generic_platform exports
        "Pins": _Pins,
        "IOStandard": _IOStandard,
        "Subsignal": _Subsignal,
        "Misc": _Misc,
        "DiffPairs": _DiffPairs,
        "Connector": _Connector,
        "Inverted": _Inverted,
        "Drive": _Drive,
        "PlatformInfo": _PlatformInfo,
        "AutoPins": _Pins,
        # Programmer stubs
        **{
            name: type(name, (), {"__init__": lambda self, *a, **kw: None})
            for name in (
                "OpenOCD", "USBBlaster", "VivadoProgrammer",
                "TinyFpgaBProgrammer", "IceStormProgrammer",
                "LatticeProgrammer", "EfinixProgrammer",
                "GowinProgrammer", "OpenFPGALoader",
                "DFUProg", "UJProg", "GenericProgrammer",
            )
        },
        # Stdlib
        "os": __import__("os"),
        "subprocess": __import__("subprocess"),
        # Prevent __main__ guard from running
        "__name__": "_litex_board_loader_exec",
        "__builtins__": __builtins__,
    }

    # Inject mock platform classes
    for name, vendor in _PLATFORM_VENDORS.items():
        ns[name] = _make_mock_platform(name, vendor)

    return ns


# ═══════════════════════════════════════════════════════════════════════
#  IO tuple parsing
# ═══════════════════════════════════════════════════════════════════════


def _classify_resource(name: str) -> str | None:
    """Classify a LiteX resource name into a type."""
    n = name.lower()
    if n in ("user_led", "led") or ("led" in n and "ctrl" not in n):
        return "led"
    if n in ("user_btn", "key", "usr_btn", "user_dip_btn", "button_1") or "btn" in n:
        return "button"
    if n in ("user_sw", "sw") or "switch" in n or "dip_sw" in n:
        return "switch"
    if n.startswith("clk") or n == "sys_clk" or n == "ext_clk":
        return "clock"
    if n == "seven_seg":
        return "seven_seg"
    if n.startswith("seven_seg_ctrl"):
        return "seven_seg_ctrl"
    return None


def _extract_io_pins(ios: tuple) -> tuple[list[str], str, str, object]:
    """Extract pins, iostandard, direction, and connector from IO args.

    Returns (pin_names, iostandard, direction, connector).
    """
    pin_names: list[str] = []
    iostandard = ""
    direction = ""
    connector = None

    for item in ios:
        if isinstance(item, _Pins):
            pin_names.extend(item.names)
            if item.dir and item.dir != "io":
                direction = item.dir
            if item.conn:
                connector = item.conn
        elif isinstance(item, _IOStandard):
            iostandard = item.name
        elif isinstance(item, _Subsignal):
            for sub in item.ios:
                if isinstance(sub, _Pins):
                    pin_names.extend(sub.names)
                    if sub.dir and sub.dir != "io":
                        direction = sub.dir
                    if sub.conn:
                        connector = sub.conn
                elif isinstance(sub, _IOStandard):
                    iostandard = sub.name
        elif isinstance(item, _DiffPairs):
            pin_names.extend(item.p)
            if item.dir and item.dir != "io":
                direction = item.dir

    return pin_names, iostandard, direction, connector


def _parse_io_as_component(
    res_name: str, res_num: int, ios: tuple, kind: str
) -> dict:
    """Convert a single _io tuple into a component dict."""
    pin_names, iostandard, direction, connector = _extract_io_pins(ios)

    if not direction:
        direction = "o" if kind == "led" else "i"

    conn_val = None
    if isinstance(connector, tuple) and len(connector) == 2:
        conn_val = list(connector)

    name = res_name
    if kind == "led" and res_name.startswith("user_"):
        name = "led"
    elif kind == "led" and "rgb" in res_name.lower():
        name = "rgb_led"
    elif kind == "button":
        if res_name in ("user_btn", "usr_btn"):
            name = "button"
        elif res_name == "key":
            name = "button"
        elif res_name == "user_dip_btn":
            name = "button"
        elif res_name.startswith("user_btn"):
            suffix = res_name[len("user_btn"):]
            if suffix:
                name = f"button_{suffix}"
            else:
                name = "button"
        elif res_name.startswith("button"):
            name = res_name
        else:
            name = "button"
    elif kind == "switch":
        name = "switch"

    return {
        "name": name,
        "number": res_num,
        "pins": pin_names,
        "direction": direction,
        "inverted": False,
        "connector": conn_val,
        "attrs": {"IOSTANDARD": iostandard} if iostandard else {},
    }


def _parse_clock_info(
    res_name: str, ios: tuple
) -> dict:
    """Extract clock info from a clock resource tuple."""
    pin_names, _, _, _ = _extract_io_pins(ios)

    freq_hz: float | None = None
    m = re.search(r"(\d+)", res_name)
    if m:
        val = int(m.group(1))
        if val < 1000:
            freq_hz = val * 1e6
        else:
            freq_hz = float(val)

    return {
        "name": res_name,
        "pin": pin_names[0] if pin_names else "",
        "inferred_hz": freq_hz,
    }


def _build_seven_seg_def(
    seg_tuples: list[tuple], ctrl_tuples: list[tuple]
) -> dict | None:
    """Build a seven_seg definition from segment and control tuples."""
    if not seg_tuples:
        return None

    has_dp = False
    for _, _, *ios in seg_tuples:
        pin_names, _, _, _ = _extract_io_pins(tuple(ios))
        if len(pin_names) == 8:
            has_dp = True
            break

    if ctrl_tuples:
        ctrl_pins: list[str] = []
        for _, _, *ios in ctrl_tuples:
            p, _, _, _ = _extract_io_pins(tuple(ios))
            ctrl_pins.extend(p)
        num_digits = max(len(ctrl_pins), 1)
        return {
            "num_digits": num_digits,
            "has_dp": has_dp,
            "is_multiplexed": True,
            "inverted": True,
            "select_inverted": True,
        }

    return {
        "num_digits": len(seg_tuples),
        "has_dp": has_dp,
        "is_multiplexed": False,
        "inverted": False,
        "select_inverted": False,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Board name / class name derivation
# ═══════════════════════════════════════════════════════════════════════


def _prettify_filename(filename: str) -> str:
    """Convert 'digilent_arty.py' to 'Digilent Arty'."""
    name = filename.replace(".py", "")
    parts = name.split("_")
    return " ".join(p.capitalize() for p in parts)


def _make_class_name(filename: str) -> str:
    """Convert 'digilent_arty.py' to 'DigilentArtyPlatform'."""
    name = filename.replace(".py", "")
    parts = name.split("_")
    return "".join(p.capitalize() for p in parts) + "Platform"


# ═══════════════════════════════════════════════════════════════════════
#  Board file parsing
# ═══════════════════════════════════════════════════════════════════════


def parse_litex_board(source: str, filename: str) -> list[dict]:
    """Parse a litex-boards platform file and return board definition dicts."""
    lines = source.split("\n")
    cleaned = []
    for line in lines:
        s = line.strip()
        if s.startswith(("import ", "from ")):
            cleaned.append("")
        else:
            cleaned.append(line)

    ns = _make_litex_namespace()
    try:
        exec(compile("\n".join(cleaned), filename, "exec"), ns)
    except Exception:
        return []

    # Find the Platform class
    platform_class = None
    for obj_name, obj in ns.items():
        if not isinstance(obj, type):
            continue
        if obj_name.startswith("_"):
            continue
        vendor = ""
        for base in getattr(obj, "__mro__", []):
            v = getattr(base, "_vendor", "")
            if v and v != "Unknown":
                vendor = v
                break
        if vendor and obj_name != "MockPlatform":
            platform_class = obj
            break

    if platform_class is None:
        return []

    # Get class-level attributes
    default_clk_name = getattr(platform_class, "default_clk_name", None)
    default_clk_period = getattr(platform_class, "default_clk_period", None)

    # Try to instantiate to get device and IO
    device = ""
    captured_io: list[tuple] = []
    try:
        instance = platform_class()
        device = getattr(instance, "device", "")
        captured_io = getattr(instance, "_captured_io", [])
    except Exception:
        pass

    # Fallback: use module-level _io
    if not captured_io:
        for var_name in ("_io", "_io_v2", "_io_v1", "_io_common"):
            val = ns.get(var_name)
            if isinstance(val, list) and val:
                captured_io = val
                break

    if not captured_io:
        return []

    # Get vendor from class hierarchy
    vendor = ""
    for base in platform_class.__mro__:
        v = getattr(base, "_vendor", "")
        if v and v != "Unknown":
            vendor = v
            break

    # Parse all IO tuples
    leds: list[dict] = []
    buttons: list[dict] = []
    switches: list[dict] = []
    clock_infos: list[dict] = []
    seg_tuples: list[tuple] = []
    seg_ctrl_tuples: list[tuple] = []

    for io_tuple in captured_io:
        if not isinstance(io_tuple, tuple) or len(io_tuple) < 3:
            continue

        res_name = str(io_tuple[0])
        try:
            res_num = int(io_tuple[1])
        except (ValueError, TypeError):
            continue
        ios = io_tuple[2:]

        kind = _classify_resource(res_name)
        if kind == "led":
            leds.append(_parse_io_as_component(res_name, res_num, ios, "led"))
        elif kind == "button":
            buttons.append(_parse_io_as_component(res_name, res_num, ios, "button"))
        elif kind == "switch":
            switches.append(_parse_io_as_component(res_name, res_num, ios, "switch"))
        elif kind == "clock":
            clock_infos.append(_parse_clock_info(res_name, ios))
        elif kind == "seven_seg":
            seg_tuples.append(io_tuple)
        elif kind == "seven_seg_ctrl":
            seg_ctrl_tuples.append(io_tuple)

    if not (leds or buttons or switches):
        return []

    # Calculate clock frequency
    default_clock_hz: float | None = None
    if (
        isinstance(default_clk_period, (int, float))
        and default_clk_period > 0
    ):
        default_clock_hz = 1e9 / default_clk_period

    # Build clock list
    clocks: list[dict] = []
    for ci in clock_infos:
        hz = ci.get("inferred_hz")
        is_default = (ci["name"] == default_clk_name) if default_clk_name else False
        if is_default and default_clock_hz:
            hz = default_clock_hz
        if hz:
            entry: dict = {"name": ci["name"], "hz": hz, "pin": ci["pin"]}
            if is_default:
                entry["is_default"] = True
            clocks.append(entry)

    if not clocks and default_clock_hz and default_clk_name:
        clocks.append({
            "name": default_clk_name,
            "hz": default_clock_hz,
            "pin": "",
            "is_default": True,
        })

    # 7-segment
    seven_seg = _build_seven_seg_def(seg_tuples, seg_ctrl_tuples)

    board_name = _prettify_filename(filename)
    class_name = _make_class_name(filename)

    return [
        {
            "name": board_name,
            "class_name": class_name,
            "vendor": vendor,
            "device": device,
            "package": "",
            "clocks": clocks,
            "default_clock_hz": default_clock_hz or 12e6,
            "leds": sorted(leds, key=lambda c: c["number"]),
            "buttons": sorted(buttons, key=lambda c: c["number"]),
            "switches": sorted(switches, key=lambda c: c["number"]),
            "seven_seg": seven_seg,
        }
    ]


# ═══════════════════════════════════════════════════════════════════════
#  Archive handling
# ═══════════════════════════════════════════════════════════════════════

_REPO = "litex-hub/litex-boards"


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
    """Download the litex-boards archive for the given git ref."""
    url = f"https://github.com/{_REPO}/archive/{ref}.tar.gz"
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(url, timeout=120) as resp:
        return bytes(resp.read())


def extract_board_files(archive_bytes: bytes) -> dict[str, str]:
    """Extract board platform .py files from the tarball."""
    board_files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            # Structure: litex-boards-{ref}/litex_boards/platforms/*.py
            if (
                len(parts) >= 4
                and parts[1] == "litex_boards"
                and parts[2] == "platforms"
                and parts[3].endswith(".py")
            ):
                filename = parts[3]
                if filename.startswith("_"):
                    continue
                f = tar.extractfile(member)
                if f is not None:
                    board_files[filename] = f.read().decode("utf-8")
    return board_files


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


def unique_name(base: str, seen: dict[str, int]) -> str:
    """Return a unique filename base, appending _2, _3, ... on collision."""
    if base not in seen:
        seen[base] = 1
        return base
    seen[base] += 1
    return f"{base}_{seen[base]}"


def generate_all_json(
    board_files: dict[str, str],
    commit_sha: str,
    schema_ref: str = "../schema/board.schema.json",
) -> dict[str, str]:
    """Parse all board files and generate JSON strings."""
    seen: dict[str, int] = {}
    results: dict[str, str] = {}
    timestamp = datetime.now(timezone.utc).isoformat()
    skipped = 0

    for filename, source in sorted(board_files.items()):
        try:
            boards = parse_litex_board(source, filename)
        except Exception as e:
            print(f"  [skip] {filename}: {e}", file=sys.stderr)
            skipped += 1
            continue

        if not boards:
            skipped += 1
            continue

        for board in boards:
            board["$schema"] = schema_ref
            board["source"] = {
                "origin": "litex-boards",
                "upstream_file": filename,
                "sync_commit": commit_sha,
                "sync_timestamp": timestamp,
            }

            base = sanitize_filename(board["name"])
            output_name = unique_name(base, seen)
            results[f"{output_name}.json"] = json.dumps(board, indent=2) + "\n"

            n_leds = len(board.get("leds", []))
            n_btns = len(board.get("buttons", []))
            n_sw = len(board.get("switches", []))
            seg_info = ""
            if board.get("seven_seg"):
                seg_info = f", {board['seven_seg']['num_digits']}-digit 7seg"
            print(
                f"  {filename} -> {output_name}.json"
                f" ({n_leds} LEDs, {n_sw} SW, {n_btns} BTN{seg_info})"
            )

    if skipped:
        print(f"  ({skipped} files skipped — no simulatable resources or parse errors)")
    return results


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
        description="Sync board definitions from litex-boards GitHub repository."
    )
    parser.add_argument(
        "--ref",
        default="master",
        help="Git ref to sync from (branch, tag, or commit SHA). Default: master",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "boards" / "litex-boards",
        help="Output directory for JSON files. Default: boards/litex-boards/",
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

    print("Extracting board files ...")
    board_files = extract_board_files(archive_bytes)
    print(f"Found {len(board_files)} board files.")

    if not board_files:
        print("No board files found in archive.", file=sys.stderr)
        return 1

    print("Generating JSON definitions ...")
    board_jsons = generate_all_json(board_files, commit_sha)
    print(f"Generated {len(board_jsons)} board definitions.")

    print(f"\nWriting to {args.output_dir} ...")
    write_outputs(args.output_dir, board_jsons, commit_sha, dry_run=args.dry_run)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
