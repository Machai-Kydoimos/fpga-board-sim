"""Multi-file designs: the folder is the project (U51).

`analyze_vhdl` used to run exactly one `-a`, so a design was one file.  That is
not what real work looks like: the course's Lab 3 ships `counter.vhd` as a
separate sub-entity, every lab folder holds a `testbench.vhd`, and the second
course's student projects are nine sources and five testbenches apiece.

Two behaviors carry the feature, and both are here: dependency order is
discovered by *retrying* rather than by parsing, and a neighbor that will not
compile is irrelevant rather than fatal.
"""

import pytest

from fpga_sim.wrapper import analyze_siblings, analyze_vhdl, find_siblings

# A top level split from its sub-entity, which is Lab 3's shape.
_COUNTER = """\
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity counter is
  generic (WIDTH : positive := 8);
  port (
    clk : in  std_logic;
    q   : out std_logic_vector(WIDTH - 1 downto 0)
  );
end entity;

architecture rtl of counter is
  signal count : unsigned(WIDTH - 1 downto 0) := (others => '0');
begin
  process (clk) begin
    if rising_edge(clk) then
      count <= count + 1;
    end if;
  end process;
  q <= std_logic_vector(count);
end architecture;
"""

# Deliberately declared *after* the thing it uses, so a naive alphabetical or
# directory-order pass would analyze it too early.  It is named to sort first.
_ALIASES = """\
library ieee;
use ieee.std_logic_1164.all;

package aliases is
  subtype byte_t is std_logic_vector(7 downto 0);
end package;
"""

_TOP = """\
library ieee;
use ieee.std_logic_1164.all;
use work.aliases.all;

entity top is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS - 1 downto 0)
  );
end entity;

architecture rtl of top is
  signal q : byte_t;
begin
  u_counter : entity work.counter
    generic map (WIDTH => 8)
    port map (clk => clk, q => q);
  led <= q(NUM_LEDS - 1 downto 0);
end architecture;
"""

# Neither compiles.  Two of the three course testbenches do not either.
_BROKEN_TB = """\
entity testbench is end entity;
architecture sim of testbench is
begin
  this is not VHDL at all
end architecture;
"""


@pytest.fixture
def lab(tmp_path):
    """A lab folder: a top level, a sub-entity, a package, a broken testbench."""
    (tmp_path / "top.vhd").write_text(_TOP, encoding="utf-8")
    (tmp_path / "counter.vhd").write_text(_COUNTER, encoding="utf-8")
    (tmp_path / "aliases.vhd").write_text(_ALIASES, encoding="utf-8")
    (tmp_path / "testbench.vhd").write_text(_BROKEN_TB, encoding="utf-8")
    return tmp_path


# ── Which files are even considered ──────────────────────────────────────────


def test_the_folder_is_the_project(lab):
    found = {p.name for p in find_siblings(lab / "top.vhd")}
    assert found == {"counter.vhd", "aliases.vhd", "testbench.vhd"}


def test_the_picked_design_is_not_its_own_sibling(lab):
    assert lab / "top.vhd" not in find_siblings(lab / "top.vhd")


def test_non_vhdl_neighbors_are_ignored(lab):
    (lab / "top.qsf").write_text("# pins", encoding="utf-8")
    (lab / "notes.md").write_text("# notes", encoding="utf-8")
    (lab / "build").mkdir()
    assert all(p.suffix in (".vhd", ".vhdl") for p in find_siblings(lab / "top.vhd"))


def test_a_design_with_no_neighbors_is_not_a_special_case(tmp_path):
    (tmp_path / "solo.vhd").write_text(_COUNTER, encoding="utf-8")
    assert find_siblings(tmp_path / "solo.vhd") == []


# ── The analysis itself ──────────────────────────────────────────────────────


@pytest.mark.slow
def test_dependency_order_is_discovered_by_retrying(lab, ghdl, tmp_path_factory):
    """`aliases` sorts first but must be analyzed before `top` uses it."""
    work = str(tmp_path_factory.mktemp("work"))
    analyzed, failures = analyze_siblings(lab / "top.vhd", work)
    assert {p.name for p in analyzed} == {"aliases.vhd", "counter.vhd"}
    assert {p.name for p in failures} == {"testbench.vhd"}


@pytest.mark.slow
def test_a_design_split_across_files_now_analyzes(lab, ghdl):
    ok, detail = analyze_vhdl(lab / "top.vhd", toplevel="top")
    assert ok, detail


@pytest.mark.slow
def test_a_broken_neighbor_does_not_block_the_design(lab, ghdl):
    """Refusing to run a student's design because the *instructor's* testbench
    is broken would be indefensible."""
    (lab / "also_broken.vhd").write_text(_BROKEN_TB.replace("testbench", "tb2"), encoding="utf-8")
    ok, detail = analyze_vhdl(lab / "top.vhd", toplevel="top")
    assert ok, detail


@pytest.mark.slow
def test_the_design_own_error_is_the_one_reported(lab, ghdl):
    """A missing sibling must not be reported as a neighbor's problem."""
    (lab / "counter.vhd").unlink()
    ok, detail = analyze_vhdl(lab / "top.vhd", toplevel="top")
    assert not ok
    assert "counter" in detail.lower()
    assert "testbench" not in detail.lower()


@pytest.mark.slow
def test_it_works_on_nvc_too(lab, nvc):
    ok, detail = analyze_vhdl(lab / "top.vhd", toplevel="top", simulator="nvc")
    assert ok, detail
