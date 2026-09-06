"""The wrapper a pin-mapped design runs inside, and the contract that picks it (U53).

The unit tests read the generated VHDL, because the interesting failures here
are silent: a segment bound to the wrong digit, an inversion missed, a boundary
bit with no driver.  The slow tests then put the same designs through GHDL and
NVC, because VHDL that reads right and does not analyze is worth nothing.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from fpga_sim.board_loader import BoardDef, discover_boards, find_board, get_default_boards_path
from fpga_sim.vhdl_contract import check_vhdl_contract
from fpga_sim.wrapper import _render_pinmap_wrapper, analyze_vhdl

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pinmap"
DE10 = FIXTURES / "de10_standard" / "test_entity.vhd"
BASYS = FIXTURES / "basys3" / "top.vhd"
_BOARDS = discover_boards(get_default_boards_path())


def _board(name: str) -> BoardDef:
    found = find_board(_BOARDS, name)
    assert found is not None, name
    return found


def _wrapper(design: Path, board_name: str) -> str:
    board = _board(board_name)
    res = check_vhdl_contract(design, board_def=board)
    assert res.ok, res.message
    assert res.pinmap is not None, "expected the constraint file to bind this design"
    return _render_pinmap_wrapper(design.stem, res.pinmap, board)


# ── What the generated VHDL says ─────────────────────────────────────────────


def test_the_contract_recognizes_a_design_by_its_constraint_file():
    res = check_vhdl_contract(DE10, board_def=_board("DE10-Standard"))
    assert res.ok
    assert res.pinmap is not None and res.pinmap.source == "test_entity.qsf"
    assert res.match is None, "a pin-mapped design is not also a convention match"
    assert "Pin map" in res.message


def test_an_active_low_button_is_inverted_by_the_board_not_the_design():
    body = _wrapper(DE10, "DE10-Standard")
    assert "reset_uut <= not btn(3);" in body


def test_an_active_low_display_is_inverted_per_segment():
    body = _wrapper(DE10, "DE10-Standard")
    assert "seg(0) <= not hex_uut(0);" in body
    # digit 1's segment a is boundary bit 8, and hex bit 7
    assert "seg(8) <= not hex_uut(7);" in body


def test_every_boundary_bit_has_exactly_one_driver():
    """A bit with no driver is dark by accident; two drivers is a resolution bug."""
    body = _wrapper(DE10, "DE10-Standard")
    board = _board("DE10-Standard")
    seg = board.seven_seg
    assert seg is not None
    for channel in range(board.num_led_channels):
        assert body.count(f"  led({channel}) <=") == 1, channel
    for bit in range(8 * seg.num_digits):
        assert body.count(f"  seg({bit}) <=") == 1, bit


def test_digits_the_design_does_not_reach_are_explicitly_dark():
    """Not merely undriven -- a line says so, which is what makes it reviewable."""
    body = _wrapper(DE10, "DE10-Standard")
    assert "seg(32) <= '0';" in body  # digit 4, segment a: outside this design's hex


def test_an_unassigned_input_is_tied_off_in_the_wrapper():
    body = _wrapper(DE10, "DE10-Standard")
    assert "button_uut <= (others => '0');  -- no pin assignment" in body


def test_a_scanned_display_is_demultiplexed_per_digit():
    body = _wrapper(BASYS, "Basys 3")
    # digit 0 shows the shared segment lines only while its enable is asserted,
    # and the enable is active-low on this board.
    assert "seg(0) <= not cathode_uut(0) when sel_uut(0) = '0' else '0';" in body
    assert "seg(8) <= not cathode_uut(0) when sel_uut(1) = '0' else '0';" in body


def test_the_wrapper_declares_numeric_std():
    """The duty integrator spliced in for Full measurement is written in it."""
    assert "use ieee.numeric_std.all;" in _wrapper(DE10, "DE10-Standard")


def test_the_wrapper_names_the_file_it_was_built_from():
    body = _wrapper(DE10, "DE10-Standard")
    assert "test_entity.qsf" in body


# ── Choosing the mechanism ───────────────────────────────────────────────────


def test_an_explicit_pinmap_file_is_used(tmp_path):
    design = tmp_path / "test_entity.vhd"
    design.write_text(DE10.read_text(encoding="utf-8"), encoding="utf-8")
    elsewhere = tmp_path / "constraints"
    elsewhere.mkdir()
    qsf = elsewhere / "board.qsf"
    qsf.write_text((DE10.parent / "test_entity.qsf").read_text(encoding="utf-8"), encoding="utf-8")
    res = check_vhdl_contract(design, board_def=_board("DE10-Standard"), pinmap=qsf)
    assert res.ok and res.pinmap is not None and res.pinmap.source == "board.qsf"


def test_a_missing_pinmap_file_is_reported(tmp_path):
    design = tmp_path / "test_entity.vhd"
    design.write_text(DE10.read_text(encoding="utf-8"), encoding="utf-8")
    res = check_vhdl_contract(design, board_def=_board("DE10-Standard"), pinmap="/nope/x.qsf")
    assert not res.ok and "not found" in res.message


def test_a_design_with_no_constraint_file_takes_the_old_path(tmp_path):
    """Nothing beside it, so the generic contract answers exactly as before."""
    design = tmp_path / "blinky.vhd"
    design.write_text(
        (Path(__file__).resolve().parent.parent / "hdl" / "blinky.vhd").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    res = check_vhdl_contract(design, board_def=_board("DE10-Standard"))
    assert res.ok and res.pinmap is None


# ── And it has to actually analyze ───────────────────────────────────────────


@pytest.mark.slow
@pytest.mark.parametrize("simulator", ["ghdl", "nvc"])
@pytest.mark.parametrize(
    ("design", "board_name"),
    [(DE10, "DE10-Standard"), (BASYS, "Basys 3")],
    ids=["de10-standard", "basys3"],
)
def test_a_pin_mapped_design_analyzes_and_elaborates(design, board_name, simulator, request):
    request.getfixturevalue(simulator)  # skips when that simulator is absent
    board = _board(board_name)
    res = check_vhdl_contract(design, board_def=board)
    assert res.ok and res.pinmap is not None
    with tempfile.TemporaryDirectory(prefix="pinmap_") as work:
        ok, detail = analyze_vhdl(
            design, work_dir=work, board_def=board, pinmap=res.pinmap, simulator=simulator
        )
    assert ok, f"{board_name} on {simulator}: {detail}"
