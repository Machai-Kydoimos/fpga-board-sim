"""
Headless integration test -- exercises board loading, GHDL analysis,
JSON serialization, and cocotb simulation without any pygame GUI.

Run with: .venv/Scripts/python sim/run_tests.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure project root is on path
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

PASS = 0
FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    tag = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    msg = f"  [{tag}] {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return ok


# ═══════════════════════════════════════════════════════════════════
# 1. Board loader tests
# ═══════════════════════════════════════════════════════════════════
print("\n=== Board Loader ===")

from board_loader import (
    discover_boards, get_default_boards_path, load_board_from_source,
    BoardDef, ComponentInfo,
)

boards_path = get_default_boards_path()
check("boards path exists", boards_path.is_dir(), str(boards_path))

boards = discover_boards(boards_path)
check("discovered boards", len(boards) > 50, f"{len(boards)} boards")

# Spot-check a well-known board
arty = [b for b in boards if "Arty A7-35" in b.name]
check("Arty A7-35 found", len(arty) == 1)
if arty:
    a = arty[0]
    check("Arty has LEDs", len(a.leds) > 0, f"{len(a.leds)} LEDs")
    check("Arty has buttons", len(a.buttons) > 0, f"{len(a.buttons)} buttons")
    check("Arty has switches", len(a.switches) > 0, f"{len(a.switches)} switches")
    check("LED has pin info", len(a.leds[0].pins) > 0, str(a.leds[0].pins))
    check("LED display_name", a.leds[0].display_name == "LED0")
    check("Arty vendor is Xilinx", a.vendor == "Xilinx", repr(a.vendor))
    check("Arty has device", a.device != "", repr(a.device))
    check("Arty has clocks", len(a.clocks) > 0, str(a.clocks))

# Named buttons (Nexys4DDR)
nexys = [b for b in boards if "Nexys4" in b.name]
if nexys:
    n = nexys[0]
    named_btns = [b for b in n.buttons if b.name != "button"]
    check("Nexys has named buttons", len(named_btns) > 0,
          ", ".join(b.display_name for b in named_btns[:3]))

# Inline board parsing
inline_src = '''
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
__all__ = ["InlineTestPlatform"]
class InlineTestPlatform(XilinxPlatform):
    resources = [
        *LEDResources(pins="A B C", attrs=Attrs(IO="TEST")),
        *SwitchResources(pins="X Y", attrs=Attrs(IO="TEST")),
    ]
'''
inline_boards = load_board_from_source(inline_src, "<inline>")
check("inline parse", len(inline_boards) == 1, inline_boards[0].name if inline_boards else "none")
if inline_boards:
    check("inline 3 LEDs",           len(inline_boards[0].leds) == 3)
    check("inline 2 switches",       len(inline_boards[0].switches) == 2)
    check("inline vendor is Xilinx", inline_boards[0].vendor == "Xilinx",
          repr(inline_boards[0].vendor))


# ═══════════════════════════════════════════════════════════════════
# 2. JSON serialization round-trip
# ═══════════════════════════════════════════════════════════════════
print("\n=== JSON Serialization ===")

test_board = BoardDef(
    name="RoundTrip", class_name="RTP",
    vendor="Xilinx", device="xc7a35ti", package="csg324",
    clocks=[100e6],
    leds=[ComponentInfo("led", "led", 0, pins=["P1"], attrs={"IO": "LVCMOS"})],
    buttons=[ComponentInfo("button", "button_up", 0, pins=["B1"],
                           connector=("pmod", 0))],
    switches=[ComponentInfo("switch", "switch", 0, pins=["S1"])],
)
j = test_board.to_json()
check("serialize to JSON", isinstance(j, str) and len(j) > 10)

parsed = json.loads(j)
check("JSON has name",      parsed["name"] == "RoundTrip")
check("JSON has vendor",    parsed["vendor"] == "Xilinx")
check("JSON has device",    parsed["device"] == "xc7a35ti")
check("JSON has clocks",    parsed["clocks"] == [100e6])
check("JSON has LED pin",   parsed["leds"][0]["pins"] == ["P1"])
check("JSON has connector", parsed["buttons"][0]["connector"] == ["pmod", 0])

# Round-trip through env
os.environ["FPGA_SIM_BOARD_JSON"] = j
rt = BoardDef.from_json(j)
check("round-trip name",          rt.name == "RoundTrip")
check("round-trip vendor",        rt.vendor == "Xilinx")
check("round-trip device",        rt.device == "xc7a35ti")
check("round-trip clocks",        rt.clocks == [100e6])
check("round-trip LED pin",       rt.leds[0].pins == ["P1"])
check("round-trip btn connector", rt.buttons[0].connector == ("pmod", 0))
del os.environ["FPGA_SIM_BOARD_JSON"]


# ═══════════════════════════════════════════════════════════════════
# 3. GHDL analysis
# ═══════════════════════════════════════════════════════════════════
print("\n=== GHDL Analysis ===")

from sim_bridge import analyze_vhdl, _find_ghdl

ghdl = _find_ghdl()
check("GHDL found", Path(ghdl).name.startswith("ghdl"), ghdl)

blinky_path = PROJECT / "hdl" / "blinky.vhd"
check("blinky.vhd exists", blinky_path.is_file())

ok, detail = analyze_vhdl(str(blinky_path))
check("blinky analyzes OK", ok, detail[:60])

# Bad VHDL should fail
bad_vhdl = tempfile.NamedTemporaryFile(suffix=".vhd", delete=False, mode="w")
bad_vhdl.write("this is not valid VHDL;\n")
bad_vhdl.close()
ok2, detail2 = analyze_vhdl(bad_vhdl.name)
check("bad VHDL fails analysis", not ok2, detail2[:60])
os.unlink(bad_vhdl.name)


# ═══════════════════════════════════════════════════════════════════
# 4. cocotb simulation (headless, no pygame)
# ═══════════════════════════════════════════════════════════════════
print("\n=== cocotb Simulation ===")

from sim_bridge import _build_sim_env

env, vpi_dll = _build_sim_env()
check("VPI DLL exists", Path(vpi_dll).is_file(), vpi_dll[-40:])

work_dir = tempfile.mkdtemp(prefix="fpga_test_ci_")

# Analyze blinky in work_dir
subprocess.run(
    [ghdl, "-a", "--std=08", "--workdir=" + work_dir, str(blinky_path)],
    env=env, check=True, cwd=work_dir,
)
check("GHDL analyze in work_dir", True)

# Run cocotb tests
cmd = [
    ghdl, "-r", "--std=08", "--workdir=" + work_dir,
    "-gNUM_SWITCHES=4", "-gNUM_BUTTONS=4", "-gNUM_LEDS=4", "-gCOUNTER_BITS=10",
    "blinky", f"--vpi={vpi_dll}",
    "--stop-time=100000ns",
]
sim_env = env.copy()
sim_env["COCOTB_TEST_MODULES"] = "test_blinky"
sim_env["TOPLEVEL"] = "blinky"
sim_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + sim_env.get("PYTHONPATH", "")

result = subprocess.run(cmd, env=sim_env, cwd=work_dir,
                        capture_output=True, text=True)

# Parse results
output = result.stdout + result.stderr
passed = output.count("PASS=")
for line in output.splitlines():
    if "PASS=" in line or "FAIL=" in line:
        print(f"  cocotb: {line.strip()}")
    if line.strip().startswith("PASS "):
        print(f"  {line.strip()}")

tests_passed = "FAIL=0" in output and "PASS=" in output
check("cocotb tests all passed", tests_passed,
      "see output above" if not tests_passed else "")

if not tests_passed:
    # Print last 20 lines for debugging
    for line in output.splitlines()[-20:]:
        print(f"  > {line}")


# ═══════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*50}")
print(f"  TOTAL: {PASS + FAIL}  PASS: {PASS}  FAIL: {FAIL}")
print(f"{'='*50}")
sys.exit(1 if FAIL else 0)
