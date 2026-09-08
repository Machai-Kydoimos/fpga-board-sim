"""Overriding a design's own generics (U48, decision D-9).

A design whose visible rate comes from the top bits of a clock divider looks
frozen here: `CNTR_LEN = 24` at 50 MHz steps three times a second on the bench
and once every minute and a half in simulation, and a student cannot tell that
from a design that does not work.

The lever is never automatic.  These tests are mostly about that: the design's
own defaults run until somebody asks for something else, and when they do, the
value reaches the *analyzer*, not just the rendered text.
"""

import pytest

from fpga_sim.board_loader import discover_boards, find_board, get_default_boards_path
from fpga_sim.generics import (
    Kind,
    design_generics,
    parse_cli_override,
    resolve,
    resolve_cli_overrides,
    validate,
)
from fpga_sim.wrapper import _render_wrapper, analyze_vhdl, wrapper_is_stale

_BOARDS = discover_boards(get_default_boards_path())

_DESIGN = """\
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity runlight is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24;
    CNTR_LEN     : positive := 24;
    INVERTED     : boolean  := false;
    SEED         : std_logic := '1';
    PATTERN      : std_logic_vector(3 downto 0) := "1010"
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS - 1 downto 0)
  );
end entity;
architecture rtl of runlight is
  signal cnt : unsigned(CNTR_LEN - 1 downto 0) := (others => '0');
begin
  process (clk) begin
    if rising_edge(clk) then cnt <= cnt + 1; end if;
  end process;
  led <= std_logic_vector(resize(cnt(CNTR_LEN - 1 downto CNTR_LEN - 1), NUM_LEDS));
end architecture;
"""


@pytest.fixture
def design(tmp_path):
    f = tmp_path / "runlight.vhd"
    f.write_text(_DESIGN, encoding="utf-8")
    return f


@pytest.fixture(scope="module")
def board():
    return find_board(_BOARDS, "DE10-Standard")


# ── What may be offered ──────────────────────────────────────────────────────


def test_generics_are_listed_in_declaration_order():
    """The author's order groups related knobs; alphabetical would scatter them."""
    names = [g.name for g in design_generics(_DESIGN, "runlight")]
    assert names == [
        "num_switches", "num_buttons", "num_leds", "counter_bits",
        "cntr_len", "inverted", "seed", "pattern",
    ]  # fmt: skip


def test_the_kinds_a_user_can_be_offered():
    by = {g.name: g for g in design_generics(_DESIGN, "runlight")}
    assert by["cntr_len"].kind == Kind.INTEGER
    assert by["inverted"].kind == Kind.BOOLEAN
    assert by["seed"].kind == Kind.BIT
    assert by["pattern"].kind == Kind.READ_ONLY  # a vector: we would be guessing


def test_the_board_sized_generics_are_not_editable():
    """Promising a width the board cannot deliver is not a thing to offer."""
    by = {g.name: g for g in design_generics(_DESIGN, "runlight")}
    assert not by["num_leds"].editable
    assert not by["num_switches"].editable


def test_counter_bits_is_editable_and_that_is_the_point():
    """The simulator already overrides it to 17 and said so nowhere."""
    by = {g.name: g for g in design_generics(_DESIGN, "runlight")}
    assert by["counter_bits"].editable


def test_a_read_only_generic_is_listed_rather_than_hidden():
    """ "You cannot change this here" is information; a blank space is not."""
    assert any(g.name == "pattern" for g in design_generics(_DESIGN, "runlight"))


def test_a_design_with_no_generics_is_not_an_error():
    assert design_generics("entity t is port (clk : in bit); end entity;", "t") == []


def test_an_unparseable_design_reports_no_generics_rather_than_raising():
    assert design_generics("this is not vhdl", "t") == []


# ── What a user may type ─────────────────────────────────────────────────────


def _defn(name):
    return next(g for g in design_generics(_DESIGN, "runlight") if g.name == name)


@pytest.mark.parametrize(
    "name,value,ok",
    [
        ("cntr_len", "4", True),
        ("cntr_len", "1_000", True),
        ("cntr_len", "0", False),  # positive
        ("cntr_len", "banana", False),
        ("inverted", "true", True),
        ("inverted", "TRUE", True),
        ("inverted", "1", False),
        ("seed", "'0'", True),
        ("seed", "0", False),  # needs the quotes
        ("pattern", '"1010"', False),  # read-only
    ],
)
def test_validation(name, value, ok):
    assert (validate(_defn(name), value) is None) is ok


def test_a_rejected_value_says_what_would_be_accepted():
    assert "whole number" in (validate(_defn("cntr_len"), "banana") or "")
    assert "true or false" in (validate(_defn("inverted"), "yes") or "")


def test_cli_pairs_are_parsed_and_bad_ones_explained():
    assert parse_cli_override("CNTR_LEN=4") == ("cntr_len", "4")
    assert "NAME=VALUE" in parse_cli_override("CNTR_LEN")
    assert "NAME=VALUE" in parse_cli_override("=4")


def test_a_name_the_design_does_not_declare_is_reported_not_ignored():
    """Silently running unchanged looks exactly like the flag not working."""
    defs = design_generics(_DESIGN, "runlight")
    accepted, problems = resolve(defs, {"NOPE": "4"})
    assert accepted == {}
    assert problems and "not a generic of this design" in problems[0]
    assert "CNTR_LEN" in problems[0]  # and here is what it does declare


# ── The value has to reach the simulator, not just the text ──────────────────


def test_the_override_is_written_into_the_wrapper(board):
    text = _render_wrapper("runlight", board_def=board, generic_overrides={"cntr_len": "4"})
    assert "CNTR_LEN => 4," in text


def test_overriding_counter_bits_replaces_the_simulator_forcing(board):
    plain = _render_wrapper("runlight", board_def=board)
    assert "COUNTER_BITS => COUNTER_BITS" in plain
    forced = _render_wrapper("runlight", board_def=board, generic_overrides={"counter_bits": "9"})
    assert "COUNTER_BITS => 9" in forced


def test_no_override_renders_exactly_what_it_always_did(board):
    """The whole feature must be free when nobody uses it."""
    assert _render_wrapper("runlight", board_def=board) == _render_wrapper(
        "runlight", board_def=board, generic_overrides={}
    )


@pytest.mark.slow
def test_an_overridden_design_actually_analyzes(design, board, ghdl):
    """A wrapper that renders is not a wrapper that analyzes."""
    ok, detail = analyze_vhdl(
        design, toplevel="runlight", board_def=board, generic_overrides={"cntr_len": "4"}
    )
    assert ok, detail


@pytest.mark.slow
def test_a_bad_value_fails_at_analysis_where_the_user_is_still_looking(design, board, ghdl):
    ok, detail = analyze_vhdl(
        design, toplevel="runlight", board_def=board, generic_overrides={"cntr_len": "0"}
    )
    assert not ok
    assert "CNTR_LEN" in detail


@pytest.mark.slow
def test_changing_an_override_re_analyzes(design, board, ghdl):
    """`wrapper_is_stale` compares the artifact, so this comes for free."""
    ok, work_dir = analyze_vhdl(
        design, toplevel="runlight", board_def=board, generic_overrides={"cntr_len": "4"}
    )
    assert ok, work_dir
    assert not wrapper_is_stale(
        work_dir, "runlight", vhdl_path=design, board_def=board,
        generic_overrides={"cntr_len": "4"},
    )  # fmt: skip
    assert wrapper_is_stale(
        work_dir, "runlight", vhdl_path=design, board_def=board,
        generic_overrides={"cntr_len": "8"},
    )  # fmt: skip
    assert wrapper_is_stale(work_dir, "runlight", vhdl_path=design, board_def=board)


# ── --generic reaches the benchmark too (B2) ─────────────────────────────────

_BIT_AND_BOOL = """
library ieee; use ieee.std_logic_1164.all;
entity picky is
  generic (WIDTH : positive := 4; MODE : boolean := true; LEVEL : std_logic := '0');
  port (clk : in std_logic; led : out std_logic_vector(1 downto 0));
end picky;
architecture rtl of picky is begin led <= (others => LEVEL); end rtl;
"""

_TINY = """
library ieee; use ieee.std_logic_1164.all;
entity tiny is
  generic (COUNTER_BITS : positive := 24);
  port (clk : in std_logic;
        sw  : in std_logic_vector(1 downto 0);
        btn : in std_logic_vector(1 downto 0);
        led : out std_logic_vector(1 downto 0));
end tiny;
architecture rtl of tiny is begin led <= sw; end rtl;
"""


def test_every_rejection_names_the_generic_it_refused():
    """On the CLI the name is the only way to tell which --generic was refused.

    The dialog shows these beside a labeled field, so it never needed them;
    ``--generic`` surfaced the same words with no field and, until B2, not at
    all. The integer messages always named it -- now all of them do.
    """
    defs = {d.name: d for d in design_generics(_BIT_AND_BOOL, "picky")}
    assert "MODE takes true or false." == validate(defs["mode"], "yes")
    assert "LEVEL takes '0' or '1', with the quotes." == validate(defs["level"], "1")
    assert "WIDTH takes a whole number." == validate(defs["width"], "wide")


def test_the_one_shot_resolver_parses_and_resolves_together():
    accepted, problems = resolve_cli_overrides(["COUNTER_BITS=18"], _TINY, "tiny")
    assert accepted == {"counter_bits": "18"}
    assert problems == []


def test_the_one_shot_resolver_reports_a_name_the_design_lacks():
    accepted, problems = resolve_cli_overrides(["NOPE=1"], _TINY, "tiny")
    assert accepted == {}
    assert len(problems) == 1 and "NOPE" in problems[0]


def test_the_one_shot_resolver_reports_a_malformed_pair():
    accepted, problems = resolve_cli_overrides(["COUNTER_BITS"], _TINY, "tiny")
    assert accepted == {}
    assert problems and "NAME=VALUE" in problems[0]


def test_no_overrides_is_not_a_problem():
    assert resolve_cli_overrides([], _TINY, "tiny") == ({}, [])


def test_the_benchmark_hands_generic_overrides_to_the_analyzer(monkeypatch):
    """B2: ``--generic`` reached the launcher and never the benchmark.

    The flag was parsed and shape-checked, then dropped: ``_run_benchmark``
    built only the board-derived generics, so the design ran its own defaults
    and the run said nothing about it.  Anything measured through
    ``--benchmark``/``--screenshots`` -- which is how this project smoke-tests a
    board, and how §10.1 of the arc plan says to check a ``CNTR_LEN`` override
    -- was silently measuring the wrong thing.

    Pinned at the seam rather than end to end: the resolution was never broken,
    nobody called it, so what matters is that the value reaches ``analyze_vhdl``.
    """
    import argparse

    from fpga_sim import __main__ as main_mod
    from fpga_sim import sim_bridge
    from fpga_sim.paths import HDL_DIR
    from fpga_sim.sim_discovery import SimulatorInfo

    stub = SimulatorInfo(
        engine="ghdl", path="/nonexistent/ghdl", backend="mcode", label="GHDL", version="stub"
    )
    monkeypatch.setattr(sim_bridge, "resolve_simulator_arg", lambda *_a, **_k: stub)

    seen: dict[str, object] = {}

    def fake_analyze(*_args, **kwargs):
        seen.update(kwargs)
        return False, "stop here -- the kwargs are the assertion"

    monkeypatch.setattr(sim_bridge, "analyze_vhdl", fake_analyze)

    args = argparse.Namespace(
        sim=None,
        board="ICEStickPlatform",
        vhdl=str(HDL_DIR / "blinky.vhd"),
        pinmap=None,
        benchmark=1,
        no_ui=True,
        screenshots=None,
        generic=["COUNTER_BITS=18"],
    )
    assert main_mod._run_benchmark(args, [stub]) == 1  # the stubbed analysis
    assert seen.get("generic_overrides") == {"counter_bits": "18"}
