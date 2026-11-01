"""Guard: the committed design x board impact matrix agrees with the product (U56).

``tests/fixtures/board_design_matrix.json`` records what every design does on
every board -- the contract verdict, each native or pin-map match, the pin
map's wrong-board hint -- plus each board's generics and one row per native
bank.  U56's later phases rewrite the board files, and each regenerates the
matrix: its diff is that phase's impact evidence.  So the file has to say what
the product says *today*, and it must not move for anything else -- in
particular not for a board's ``source`` block, which those phases fill with
identity fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gen_board_design_matrix as matrix
import pytest

from fpga_sim.board_loader import discover_boards, find_board
from fpga_sim.paths import BOARDS_DIR, HDL_DIR, REPO_ROOT
from fpga_sim.vhdl_contract import check_vhdl_contract

PINMAP = REPO_ROOT / "tests" / "fixtures" / "pinmap"

#: Cheap designs covering each path a design can run by: the generic contract,
#: a native match (on six boards, three sources), and a pin map whose rejections
#: carry the wrong-board hint on most of the fleet.
_SAMPLE = [
    HDL_DIR / "blinky.vhd",
    HDL_DIR / "native" / "arty_rgb.vhd",
    PINMAP / "de10_standard" / "test_entity.vhd",
]


def _built(boards_dir: Path, designs: list[Path]) -> dict[str, Any]:
    """The matrix for *boards_dir* and *designs*, as the committed file would parse."""
    parsed: dict[str, Any] = json.loads(matrix.render(matrix.collect(boards_dir, designs)))
    return parsed


def test_the_matrix_is_up_to_date(capsys: pytest.CaptureFixture[str]) -> None:
    status = matrix.main(["--check"])
    out = capsys.readouterr().out
    assert status == 0, (
        f"{out}\nRegenerate with `{matrix.REGENERATE}` and commit it: the diff is this "
        "change's impact evidence, so read it before you do."
    )


def test_the_wrong_board_hint_detector_still_hears_the_product() -> None:
    """The product keeps no flag for the hint, so the matrix spots its sentence.

    A DE10-Standard ``.qsf`` (a Cyclone V part) against the Basys 3 (an Artix-7)
    is the textbook wrong board.  If ``fpga_sim.pinmap`` rewords the hint, this
    fails here, rather than the matrix quietly losing every hint it records.
    """
    board = find_board(discover_boards(BOARDS_DIR), "digilent-xdc/basys_3")
    assert board is not None
    result = check_vhdl_contract(PINMAP / "de10_standard" / "test_entity.vhd", board_def=board)
    assert not result.ok
    assert matrix.wrong_board_hint_fired(result), result.message


def test_a_boards_source_block_does_not_reach_the_matrix(tmp_path: Path) -> None:
    """Identity fields land in every board's ``source`` block; the matrix must not move.

    Every board file is copied with its ``source`` block replaced, and the
    matrix built from the copies must equal the one built from the real files.
    """
    boards = tmp_path / "boards"
    for key in matrix.board_files(BOARDS_DIR):
        data = json.loads((BOARDS_DIR / f"{key}.json").read_text(encoding="utf-8"))
        data["source"] = {
            "repo": "https://example.invalid/elsewhere",
            "upstream_class": "SomewhereElsePlatform",
            "upstream_status": "orphaned",
        }
        dest = boards / f"{key}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data), encoding="utf-8")

    assert _built(boards, _SAMPLE) == _built(BOARDS_DIR, _SAMPLE)


def test_a_board_file_the_loader_cannot_read_keeps_its_line(tmp_path: Path) -> None:
    """A board dropping out of the fleet shows as a changed line, not a silent gap."""
    boards = tmp_path / "boards"
    custom = boards / "custom"
    custom.mkdir(parents=True)
    real = (BOARDS_DIR / "custom" / "de10_standard.json").read_text(encoding="utf-8")
    (custom / "de10_standard.json").write_text(real, encoding="utf-8")
    (custom / "broken.json").write_text("{ not json", encoding="utf-8")
    # Neither of these is a board: the sync's ledger and the schema directory.
    (custom / "_sync_metadata.json").write_text("{}", encoding="utf-8")
    (boards / "schema").mkdir()
    (boards / "schema" / "board.schema.json").write_text("{}", encoding="utf-8")

    built = _built(boards, [HDL_DIR / "blinky.vhd"])

    assert built["boards"]["custom/broken"] == matrix.NOT_LOADED
    assert set(built["boards"]) == {"custom/broken", "custom/de10_standard"}
    assert built["counts"]["board_files"] == 2
    assert built["counts"]["boards_loaded"] == 1
    assert set(built["native_banks"]) == {"custom/de10_standard"}
    assert built["designs"]["hdl/blinky.vhd"] == {"generic": {"all_except": []}}


def test_a_minimal_design_carries_only_what_the_matcher_demands() -> None:
    """Its clock and the bank, plus an LED floor and every declared input bank."""
    bank = {"name": "x", "width": 1}
    block = {
        "clk": "clk",
        "description": "not a role",
        "leds": bank,
        "leds_green": bank,
        "leds_rgb": {"names": ["r", "g", "b"]},
        "switches": bank,
        "buttons": bank,
        "seven_seg": {"style": "individual"},
    }
    assert set(matrix.minimal_block(block, "leds")) == {"clk", "leds", "switches", "buttons"}
    assert set(matrix.minimal_block(block, "leds_rgb")) == {
        "clk",
        "leds_rgb",
        "switches",
        "buttons",
    }
    assert set(matrix.minimal_block(block, "leds_green")) == {
        "clk",
        "leds_green",
        "leds",
        "switches",
        "buttons",
    }
    rgb_only = {"clk": "clk", "leds_rgb": {"names": ["r", "g", "b"]}, "buttons": bank}
    assert set(matrix.minimal_block(rgb_only, "buttons")) == {"clk", "buttons", "leds_rgb"}
