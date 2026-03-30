"""Tests for sim_bridge error paths and error message quality.

Verifies that:
  - check_vhdl_encoding() / check_vhdl_contract() return (False, msg) rather
    than raising when given bad input.
  - Error messages name the relevant identifier (port, entity, line) so users
    know what to fix.
  - analyze_vhdl() handles missing/broken VHDL gracefully.
"""

from pathlib import Path

import pytest

from sim_bridge import analyze_vhdl, check_vhdl_contract, check_vhdl_encoding

HDL = Path(__file__).resolve().parent.parent / "hdl"


# ── check_vhdl_encoding: missing file ─────────────────────────────────────────


def test_encoding_missing_file_returns_false(tmp_path):
    ok, msg = check_vhdl_encoding(tmp_path / "nonexistent.vhd")
    assert not ok


def test_encoding_missing_file_returns_nonempty_message(tmp_path):
    _, msg = check_vhdl_encoding(tmp_path / "nonexistent.vhd")
    assert msg


# ── check_vhdl_encoding: non-ASCII line number ────────────────────────────────


def test_encoding_nonascii_message_contains_line_number(tmp_path):
    """Non-ASCII error must report the exact line number."""
    vhd = tmp_path / "nonascii.vhd"
    # Line 1 is pure ASCII; line 2 contains a non-ASCII byte (é = 0xC3 0xA9)
    vhd.write_bytes(b"-- ascii line\n-- caf\xc3\xa9\n")
    ok, msg = check_vhdl_encoding(vhd)
    assert not ok
    assert "2" in msg


def test_encoding_nonascii_on_first_line_reports_line_1(tmp_path):
    vhd = tmp_path / "line1.vhd"
    vhd.write_bytes(b"\xff bad\n")
    ok, msg = check_vhdl_encoding(vhd)
    assert not ok
    assert "1" in msg


# ── check_vhdl_contract: missing file ────────────────────────────────────────


def test_contract_missing_file_returns_false(tmp_path):
    ok, _ = check_vhdl_contract(tmp_path / "nonexistent.vhd")
    assert not ok


def test_contract_missing_file_returns_nonempty_message(tmp_path):
    _, msg = check_vhdl_contract(tmp_path / "nonexistent.vhd")
    assert msg


# ── check_vhdl_contract: entity mismatch message quality ─────────────────────


def test_contract_entity_mismatch_message_names_found_entity(tmp_path):
    """The error must name the entity that was found."""
    vhd = tmp_path / "widget.vhd"
    vhd.write_text(
        "entity gadget is\n"
        "  port (clk: in bit; sw: in bit; btn: in bit; led: out bit);\n"
        "end entity;\n"
    )
    _, msg = check_vhdl_contract(vhd)
    assert "gadget" in msg


def test_contract_entity_mismatch_message_names_expected_stem(tmp_path):
    """The error must also name the filename stem so the user knows the expectation."""
    vhd = tmp_path / "widget.vhd"
    vhd.write_text(
        "entity gadget is\n"
        "  port (clk: in bit; sw: in bit; btn: in bit; led: out bit);\n"
        "end entity;\n"
    )
    _, msg = check_vhdl_contract(vhd)
    assert "widget" in msg


# ── check_vhdl_contract: missing port message quality ────────────────────────


def test_contract_missing_clk_message_names_clk(tmp_path):
    """Missing 'clk' port error must identify 'clk' explicitly."""
    vhd = tmp_path / "noclk.vhd"
    vhd.write_text(
        "entity noclk is\n  port (sw: in bit; btn: in bit; led: out bit);\nend entity;\n"
    )
    ok, msg = check_vhdl_contract(vhd)
    assert not ok
    assert "clk" in msg.lower()


def test_contract_missing_led_message_names_led(tmp_path):
    """Missing 'led' port error must identify 'led' explicitly."""
    vhd = tmp_path / "noled.vhd"
    vhd.write_text("entity noled is\n  port (clk: in bit; sw: in bit; btn: in bit);\nend entity;\n")
    ok, msg = check_vhdl_contract(vhd)
    assert not ok
    assert "led" in msg.lower()


def test_contract_missing_sw_message_names_sw(tmp_path):
    """Missing 'sw' port error must identify 'sw' explicitly."""
    vhd = tmp_path / "nosw.vhd"
    vhd.write_text(
        "entity nosw is\n  port (clk: in bit; btn: in bit; led: out bit);\nend entity;\n"
    )
    ok, msg = check_vhdl_contract(vhd)
    assert not ok
    assert "sw" in msg.lower()


# ── check_vhdl_contract: bad_contract_blinky.vhdl fixture ────────────────────


def test_bad_contract_message_names_mismatched_entity():
    """bad_contract_blinky.vhdl has entity 'blinky'; error must mention it."""
    _, msg = check_vhdl_contract(HDL / "bad_contract_blinky.vhdl")
    assert "blinky" in msg


def test_bad_contract_message_names_expected_filename_stem():
    """bad_contract_blinky.vhdl error must mention 'bad_contract_blinky'."""
    _, msg = check_vhdl_contract(HDL / "bad_contract_blinky.vhdl")
    assert "bad_contract_blinky" in msg


# ── analyze_vhdl: error path quality ─────────────────────────────────────────


@pytest.mark.slow
def test_analyze_bad_syntax_returns_false(tmp_path):
    """Syntactically broken VHDL must return ok=False."""
    vhd = tmp_path / "broken.vhd"
    vhd.write_text("this is not valid vhdl !!!\n")
    ok, _ = analyze_vhdl(vhd, toplevel="broken")
    assert not ok


@pytest.mark.slow
def test_analyze_bad_syntax_returns_nonempty_error(tmp_path):
    """Syntax errors must produce a non-empty error string."""
    vhd = tmp_path / "broken.vhd"
    vhd.write_text("this is not valid vhdl !!!\n")
    _, msg = analyze_vhdl(vhd, toplevel="broken")
    assert msg
