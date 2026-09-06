"""The project pin map (U53): a design run through its own constraint file.

The rules under test are mostly the ones Gate A found in real course material
rather than the ones the design sketch predicted -- an input with no assignment
at all, a constraint file that describes the whole board rather than the
design, and a design that drives part of a display.
"""

from __future__ import annotations

import pytest

from fpga_sim.board_loader import BoardDef, discover_boards, find_board, get_default_boards_path
from fpga_sim.constraints import qsf, xdc
from fpga_sim.paths import HDL_DIR
from fpga_sim.pinmap import (
    PinMapMatch,
    PinMapProblem,
    board_pin_index,
    build_pin_map,
    discover_pinmap,
    nearby_pinmaps,
    normalize_pin,
    read_pinmap,
    split_port,
)
from fpga_sim.vhdl_contract import check_vhdl_contract
from fpga_sim.vhdl_interface import _parse_toplevel_interface

_BOARDS = discover_boards(get_default_boards_path())


def _board(name: str) -> BoardDef:
    found = find_board(_BOARDS, name)
    assert found is not None, name
    return found


def _map(
    vhdl: str, stem: str, constraints: str, board_name: str, **kw: str
) -> PinMapMatch | PinMapProblem:
    parsed = _parse_toplevel_interface(vhdl, stem)
    assert parsed is not None, "the fixture's entity must parse"
    dialect = xdc if "PACKAGE_PIN" in constraints else qsf
    return build_pin_map(parsed[0], dialect.parse(constraints), _board(board_name), **kw)


# ── Spelling ─────────────────────────────────────────────────────────────────


def test_a_pin_is_the_same_pad_however_it_is_spelled():
    """Quartus writes PIN_AF14 in assignments; the board data stores AF14."""
    assert normalize_pin("PIN_AF14") == normalize_pin("AF14") == "af14"
    assert normalize_pin("  pin_W5 ") == "w5"


def test_a_port_token_splits_into_name_and_bit():
    assert split_port("LED_R[3]") == ("led_r", 3)
    assert split_port("CLOCK") == ("clock", None)
    assert split_port("seg [ 6 ]") == ("seg", 6)


# ── The board's side ─────────────────────────────────────────────────────────


def test_the_board_index_knows_what_each_pin_drives():
    index = board_pin_index(_board("DE10-Standard"))
    assert index["af14"].kind == "clk"
    assert index["aa24"] == board_pin_index(_board("DE10-Standard"))["aa24"]
    assert index["aa24"].kind == "led" and index["aa24"].index == 0
    assert index["ab30"].kind == "sw" and index["ab30"].index == 0
    btn3 = index["aa15"]
    assert btn3.kind == "btn" and btn3.index == 3 and btn3.active_low


def test_a_directly_driven_display_indexes_by_digit_and_segment():
    index = board_pin_index(_board("DE10-Standard"))
    assert index["w17"].kind == "seg"
    assert index["w17"].digit == 0 and index["w17"].segment == 0
    assert index["ab21"].digit == 5 and index["ab21"].segment == 6


def test_a_scanned_display_shares_its_segments_across_digits():
    index = board_pin_index(_board("Basys 3"))
    assert index["w7"].kind == "seg" and index["w7"].digit is None
    assert index["u2"].kind == "digit_enable" and index["u2"].index == 0
    assert index["v7"].kind == "dp"


def test_a_board_without_pin_data_simply_indexes_less():
    """No pins is not an error; it only means this board cannot be targeted."""
    bare = BoardDef(name="Bare", class_name="BarePlatform")
    assert board_pin_index(bare) == {}


# ── Finding the file ─────────────────────────────────────────────────────────


def test_one_constraint_file_beside_the_design_is_used(tmp_path):
    (tmp_path / "top.vhd").write_text("-- design", encoding="utf-8")
    qsf_file = tmp_path / "top.qsf"
    qsf_file.write_text("set_location_assignment PIN_W5 -to clk", encoding="utf-8")
    assert discover_pinmap(tmp_path / "top.vhd") == qsf_file


def test_no_constraint_file_is_not_an_error(tmp_path):
    """The name-based paths still run; this is just not a pin-map project."""
    (tmp_path / "top.vhd").write_text("-- design", encoding="utf-8")
    assert discover_pinmap(tmp_path / "top.vhd") is None


def test_two_constraint_files_ask_rather_than_guess(tmp_path):
    """A folder with both a .qsf and an .xdc is targeting two boards."""
    (tmp_path / "top.vhd").write_text("-- design", encoding="utf-8")
    (tmp_path / "top.qsf").write_text("", encoding="utf-8")
    (tmp_path / "top.xdc").write_text("", encoding="utf-8")
    problem = discover_pinmap(tmp_path / "top.vhd")
    assert isinstance(problem, PinMapProblem)
    assert "top.qsf" in problem.message and "top.xdc" in problem.message
    assert "--pinmap" in problem.message


# ── The folder contract, and the one thing it owes the user ──────────────────
#
# One folder is one project.  discover_pinmap looks in exactly one directory
# and nowhere else, deliberately: Vivado's layout is user-configurable and
# version-dependent, so a tool that learned it would be wrong again on the next
# release.  What that costs is a student who opens a Vivado project and lands
# three directories from their own .xdc -- so nearby_pinmaps finds it, **for a
# message only**, and never to build a map from.


def _vivado_project(root):
    """Lay out a Vivado project the way Vivado lays one out."""
    srcs = root / "counter" / "counter.srcs"
    (srcs / "sources_1" / "new").mkdir(parents=True)
    (srcs / "constrs_1" / "new").mkdir(parents=True)
    design = srcs / "sources_1" / "new" / "top.vhd"
    design.write_text("-- design", encoding="utf-8")
    xdc_file = srcs / "constrs_1" / "new" / "Basys3_Master.xdc"
    xdc_file.write_text("# constraints", encoding="utf-8")
    return design, xdc_file


def test_a_constraint_file_sideways_in_a_vivado_project_is_found(tmp_path):
    design, xdc_file = _vivado_project(tmp_path)
    assert discover_pinmap(design) is None  # not in the folder, so not used
    assert nearby_pinmaps(design) == (xdc_file,)


def test_a_build_artifact_is_never_offered(tmp_path):
    """`.runs` holds copies; a hit there would be output, not intent."""
    design, xdc_file = _vivado_project(tmp_path)
    runs = tmp_path / "counter" / "counter.runs" / "impl_1"
    runs.mkdir(parents=True)
    (runs / "decoy.xdc").write_text("# artifact", encoding="utf-8")
    assert nearby_pinmaps(design) == (xdc_file,)


def test_the_search_never_reaches_into_the_lab_next_door(tmp_path):
    """The whole reason it anchors on a project root rather than on depth."""
    for lab in ("lab1", "lab2"):
        (tmp_path / lab / "rtl").mkdir(parents=True)
        (tmp_path / lab / f"{lab}.qsf").write_text("# qsf", encoding="utf-8")
        (tmp_path / lab / "rtl" / "top.vhd").write_text("-- design", encoding="utf-8")
    found = nearby_pinmaps(tmp_path / "lab2" / "rtl" / "top.vhd")
    assert found == (tmp_path / "lab2" / "lab2.qsf",)


def test_a_loose_folder_with_no_project_around_it_says_nothing(tmp_path):
    """No project root means no claim about what belongs to this design."""
    (tmp_path / "loose").mkdir()
    design = tmp_path / "loose" / "top.vhd"
    design.write_text("-- design", encoding="utf-8")
    (tmp_path / "somewhere.xdc").write_text("# not ours", encoding="utf-8")
    assert nearby_pinmaps(design) == ()


def test_xml_is_read_beside_a_design_but_never_guessed_at(tmp_path):
    """BoardStore writes .xml, and so does half the software ever shipped."""
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "proj.qpf").write_text("# quartus project", encoding="utf-8")
    design = proj / "rtl" / "top.vhd"
    design.write_text("-- design", encoding="utf-8")
    (proj / "settings.xml").write_text("<xml/>", encoding="utf-8")
    assert nearby_pinmaps(design) == ()

    beside = proj / "rtl" / "board.xml"
    beside.write_text("<xml/>", encoding="utf-8")
    assert discover_pinmap(design) == beside  # deliberate, so honored


def test_the_design_own_folder_is_not_nearby(tmp_path):
    """That is discover_pinmap's job, and it reports differently."""
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "proj.qpf").write_text("# quartus project", encoding="utf-8")
    design = proj / "rtl" / "top.vhd"
    design.write_text("-- design", encoding="utf-8")
    own = proj / "rtl" / "own.qsf"
    own.write_text("# qsf", encoding="utf-8")
    assert own not in nearby_pinmaps(design)


def test_a_rejected_design_is_told_where_its_constraint_file_is(tmp_path):
    """The message is the entire point of the search."""
    design, xdc_file = _vivado_project(tmp_path)
    design.write_text(
        "library ieee;\nuse ieee.std_logic_1164.all;\n"
        "entity top is port (clkin : in std_logic; lamps : out std_logic_vector(3 downto 0));"
        "\nend entity;\narchitecture rtl of top is begin lamps <= (others => '0'); end;\n",
        encoding="utf-8",
    )
    result = check_vhdl_contract(design, _board("Basys 3"))
    assert not result.ok
    assert str(xdc_file) in result.message
    assert "One folder is one project" in result.message
    # the original diagnosis is kept, not replaced
    assert "clk" in result.message


def test_a_design_that_runs_is_never_nagged(tmp_path):
    """Advice on a working design is noise, however true it is."""
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "proj.qpf").write_text("# quartus project", encoding="utf-8")
    (proj / "board.xdc").write_text("# constraints", encoding="utf-8")
    design = proj / "rtl" / "blinky.vhd"
    design.write_text(
        (HDL_DIR / "blinky.vhd").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = check_vhdl_contract(design, _board("Basys 3"))
    assert result.ok
    assert "One folder is one project" not in result.message


def test_an_unreadable_dialect_is_reported_not_guessed(tmp_path):
    odd = tmp_path / "top.sdc"
    odd.write_text("create_clock -period 10", encoding="utf-8")
    problem = read_pinmap(odd)
    assert isinstance(problem, PinMapProblem) and "top.sdc" in problem.message


# ── The map ──────────────────────────────────────────────────────────────────

_LAB_VHDL = """
library ieee; use ieee.std_logic_1164.all;
entity test_entity is
  port (clock : in std_logic;
        reset : in std_logic;
        button : in std_logic_vector(2 downto 0);
        sw : in std_logic_vector(9 downto 0);
        led_r : out std_logic_vector(9 downto 0);
        hex : out std_logic_vector(27 downto 0));
end test_entity;
"""

_LAB_QSF_PINS = {
    "CLOCK": "AF14",
    "RESET": "AA15",
    **{
        f"SW[{i}]": p
        for i, p in enumerate("AB30 Y27 AB28 AC30 W25 V25 AC28 AD30 AC29 AA30".split())
    },
    **{
        f"LED_R[{i}]": p
        for i, p in enumerate("AA24 AB23 AC23 AD24 AG25 AF25 AE24 AF24 AB22 AC22".split())
    },
    **{
        f"HEX[{i}]": p
        for i, p in enumerate(
            "W17 V18 AG17 AG16 AH17 AG18 AH18 AF16 V16 AE16 AD17 AE18 AE17 V17 "
            "AA21 AB17 AA18 Y17 Y18 AF18 W16 Y19 W19 AD19 AA20 AC20 AA19 AD20".split()
        )
    },
}
_LAB_QSF = "\n".join(f"set_location_assignment PIN_{p} -to {n}" for n, p in _LAB_QSF_PINS.items())


def test_a_lab_design_maps_through_its_own_qsf():
    result = _map(_LAB_VHDL, "test_entity", _LAB_QSF, "DE10-Standard", source="test_entity.qsf")
    assert isinstance(result, PinMapMatch)
    assert result.clock_port == "clock"
    assert len(result.inputs) == 11  # reset + 10 switches
    assert len(result.outputs) == 38  # 10 LEDs + 28 segments


def test_each_display_bit_lands_on_its_own_digit_and_segment():
    """The failure this guards against is silent: wrong digit, plausible picture."""
    result = _map(_LAB_VHDL, "test_entity", _LAB_QSF, "DE10-Standard", source="q.qsf")
    assert isinstance(result, PinMapMatch)
    segs = [b for b in result.outputs if b.role.kind == "seg"]
    assert len(segs) == 28
    for b in segs:
        assert b.bit is not None
        assert b.role.digit == b.bit // 7, b
        assert b.role.segment == b.bit % 7, b


def test_polarity_comes_from_the_board_not_the_design():
    """KEY[3] is active-low on this board; the design cannot say otherwise."""
    result = _map(_LAB_VHDL, "test_entity", _LAB_QSF, "DE10-Standard", source="q.qsf")
    assert isinstance(result, PinMapMatch)
    reset = [b for b in result.inputs if b.port == "reset"]
    assert len(reset) == 1
    assert reset[0].role.kind == "btn" and reset[0].role.index == 3
    assert reset[0].role.active_low


def test_an_input_with_no_assignment_ties_off_with_a_note():
    """Gate A: a real lab top level declares `button` its own .qsf never binds.

    Quartus places such a pin automatically, so the project builds and nobody
    finds out.  Rejecting it would refuse the first file of the first lab.
    """
    result = _map(_LAB_VHDL, "test_entity", _LAB_QSF, "DE10-Standard", source="test_entity.qsf")
    assert isinstance(result, PinMapMatch)
    assert result.tied_inputs == ("button",)
    assert any("button" in n and "test_entity.qsf" in n for n in result.notes)


def test_a_design_may_drive_only_part_of_the_display():
    """Four digits of a six-digit board; the rest stay dark, as on the bench."""
    result = _map(_LAB_VHDL, "test_entity", _LAB_QSF, "DE10-Standard", source="q.qsf")
    assert isinstance(result, PinMapMatch)
    driven = {b.role.digit for b in result.outputs if b.role.kind == "seg"}
    assert driven == {0, 1, 2, 3}
    seg = _board("DE10-Standard").seven_seg
    assert seg is not None and seg.num_digits == 6


def test_assignments_the_design_never_declares_are_ignored():
    """The .qsf is the vendor's whole pin file: 422 lines against six ports."""
    noisy = (
        _LAB_QSF
        + "\n"
        + "\n".join(
            f"set_location_assignment PIN_{p} -to DRAM_ADDR[{i}]"
            for i, p in enumerate(["AK14", "AH14", "AG15", "AE14"])
        )
    )
    result = _map(_LAB_VHDL, "test_entity", noisy, "DE10-Standard", source="q.qsf")
    assert isinstance(result, PinMapMatch), getattr(result, "message", "")


def test_an_output_with_no_assignment_is_left_open():
    vhdl = _LAB_VHDL.replace(
        "hex : out std_logic_vector(27 downto 0));",
        "hex : out std_logic_vector(27 downto 0);\n        spare : out std_logic);",
    )
    result = _map(vhdl, "test_entity", _LAB_QSF, "DE10-Standard", source="q.qsf")
    assert isinstance(result, PinMapMatch)
    assert "spare" in result.open_outputs


def test_an_unassigned_input_with_a_default_is_silent():
    """It already says what it should read, exactly as the generic contract allows."""
    vhdl = _LAB_VHDL.replace(
        "reset : in std_logic;", "reset : in std_logic;\n        uart_rx : in std_logic := '1';"
    )
    result = _map(vhdl, "test_entity", _LAB_QSF, "DE10-Standard", source="q.qsf")
    assert isinstance(result, PinMapMatch)
    assert "uart_rx" not in result.tied_inputs
    assert not any("uart_rx" in n for n in result.notes)


def test_a_pin_the_board_does_not_have_names_the_port_and_the_pin():
    bad = _LAB_QSF + "\nset_location_assignment PIN_ZZ99 -to LED_R[0]"
    bad = bad.replace("set_location_assignment PIN_AA24 -to LED_R[0]\n", "")
    result = _map(_LAB_VHDL, "test_entity", bad, "DE10-Standard", source="q.qsf")
    assert isinstance(result, PinMapProblem)
    assert "led_r[0]" in result.message.lower() and "ZZ99" in result.message


def test_a_constraint_file_for_another_board_says_so():
    """The device line is the precise signal, so the message names it."""
    result = _map(
        _LAB_VHDL,
        "test_entity",
        _LAB_QSF,
        "DE10-Lite",
        source="test_entity.qsf",
        device="5CSXFC6D6F31C6",
    )
    assert isinstance(result, PinMapProblem)
    assert "5CSXFC6D6F31C6" in result.message
    assert "wrong board" in result.message


def test_a_design_that_lights_nothing_is_refused():
    vhdl = """
    library ieee; use ieee.std_logic_1164.all;
    entity top is port (clk : in std_logic; sw : in std_logic_vector(1 downto 0)); end top;
    """
    cons = (
        "set_location_assignment PIN_AF14 -to clk\n"
        "set_location_assignment PIN_AB30 -to sw[0]\n"
        "set_location_assignment PIN_Y27 -to sw[1]\n"
    )
    result = _map(vhdl, "top", cons, "DE10-Standard", source="top.qsf")
    assert isinstance(result, PinMapProblem)
    assert "nothing to watch" in result.message


def test_a_combinational_design_needs_no_clock():
    """Task 3a is pure combinational logic and is a legitimate lab exercise."""
    vhdl = """
    library ieee; use ieee.std_logic_1164.all;
    entity top is
      port (sw : in std_logic_vector(3 downto 0); led_r : out std_logic_vector(0 downto 0));
    end top;
    """
    cons = (
        "\n".join(
            f"set_location_assignment PIN_{p} -to sw[{i}]"
            for i, p in enumerate("AB30 Y27 AB28 AC30".split())
        )
        + "\nset_location_assignment PIN_AA24 -to led_r[0]\n"
    )
    result = _map(vhdl, "top", cons, "DE10-Standard", source="top.qsf")
    assert isinstance(result, PinMapMatch)
    assert result.clock_port == ""
    assert len(result.outputs) == 1


# ── The other dialect, and the other display shape ───────────────────────────

_BASYS_XDC = """
set_property -dict { PACKAGE_PIN W5   IOSTANDARD LVCMOS33 } [get_ports clk_i]
set_property -dict { PACKAGE_PIN U16  IOSTANDARD LVCMOS33 } [get_ports {lamps[0]}]
set_property -dict { PACKAGE_PIN E19  IOSTANDARD LVCMOS33 } [get_ports {lamps[1]}]
set_property -dict { PACKAGE_PIN V17  IOSTANDARD LVCMOS33 } [get_ports {dip[0]}]
set_property -dict { PACKAGE_PIN U18  IOSTANDARD LVCMOS33 } [get_ports go]
set_property -dict { PACKAGE_PIN W7   IOSTANDARD LVCMOS33 } [get_ports {cathode[0]}]
set_property -dict { PACKAGE_PIN W6   IOSTANDARD LVCMOS33 } [get_ports {cathode[1]}]
set_property -dict { PACKAGE_PIN U8   IOSTANDARD LVCMOS33 } [get_ports {cathode[2]}]
set_property -dict { PACKAGE_PIN V8   IOSTANDARD LVCMOS33 } [get_ports {cathode[3]}]
set_property -dict { PACKAGE_PIN U5   IOSTANDARD LVCMOS33 } [get_ports {cathode[4]}]
set_property -dict { PACKAGE_PIN V5   IOSTANDARD LVCMOS33 } [get_ports {cathode[5]}]
set_property -dict { PACKAGE_PIN U7   IOSTANDARD LVCMOS33 } [get_ports {cathode[6]}]
set_property -dict { PACKAGE_PIN U2   IOSTANDARD LVCMOS33 } [get_ports {sel[0]}]
set_property -dict { PACKAGE_PIN U4   IOSTANDARD LVCMOS33 } [get_ports {sel[1]}]
set_property -dict { PACKAGE_PIN V4   IOSTANDARD LVCMOS33 } [get_ports {sel[2]}]
set_property -dict { PACKAGE_PIN W4   IOSTANDARD LVCMOS33 } [get_ports {sel[3]}]
set_property -dict { PACKAGE_PIN V7   IOSTANDARD LVCMOS33 } [get_ports point]
"""

_BASYS_VHDL = """
library ieee; use ieee.std_logic_1164.all;
entity top is
  port (clk_i : in std_logic;
        dip : in std_logic_vector(0 downto 0);
        go : in std_logic;
        lamps : out std_logic_vector(1 downto 0);
        cathode : out std_logic_vector(6 downto 0);
        sel : out std_logic_vector(3 downto 0);
        point : out std_logic);
end top;
"""


def test_a_scan_design_maps_through_an_xdc_with_names_of_its_own():
    """No name in this design resembles the board's; only the pins match."""
    result = _map(_BASYS_VHDL, "top", _BASYS_XDC, "Basys 3", source="top.xdc")
    assert isinstance(result, PinMapMatch)
    assert result.clock_port == "clk_i"
    kinds = sorted(b.role.kind for b in result.outputs)
    assert kinds.count("seg") == 7
    assert kinds.count("digit_enable") == 4
    assert kinds.count("dp") == 1
    assert kinds.count("led") == 2
    assert all(b.role.digit is None for b in result.outputs if b.role.kind == "seg")


@pytest.mark.parametrize("board_name", ["DE10-Standard", "Basys 3"])
def test_every_target_board_can_be_indexed(board_name):
    index = board_pin_index(_board(board_name))
    kinds = {role.kind for role in index.values()}
    assert {"clk", "led", "sw", "btn", "seg"} <= kinds, kinds
