"""Guard: the repository root is derived in exactly one place (roadmap D17).

``Path(__file__).parent.parent.parent`` counts directories between a module and
the repository root, so it is correct only for a module at a particular depth
and fails *silently* when one moves -- it still imports, still type-checks, and
starts pointing at ``src/``.  Eight of them had accumulated across five modules,
two on the path a user's VHDL travels.  :mod:`fpga_sim.paths` now owns the
count; this file keeps it that way.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from fpga_sim.paths import BOARDS_DIR, HDL_DIR, REPO_ROOT, SIM_DIR, VENV_DIR

SRC = REPO_ROOT / "src" / "fpga_sim"


def test_repo_root_is_the_directory_holding_src():
    assert (REPO_ROOT / "src" / "fpga_sim" / "paths.py").is_file()
    assert (REPO_ROOT / "pyproject.toml").is_file()


@pytest.mark.parametrize(
    ("name", "path"),
    [("HDL_DIR", HDL_DIR), ("BOARDS_DIR", BOARDS_DIR), ("SIM_DIR", SIM_DIR)],
)
def test_tree_constants_point_at_real_directories(name: str, path: Path) -> None:
    assert path.is_dir(), f"{name} -> {path}"


def test_the_trees_hold_what_their_names_claim():
    """A path that exists but points somewhere else would pass the check above."""
    assert (HDL_DIR / "blinky.vhd").is_file()
    assert (BOARDS_DIR / "schema" / "board.schema.json").is_file()
    assert (SIM_DIR / "sim_wrapper_template.vhd").is_file()


def test_venv_dir_is_named_even_when_absent():
    """A CI checkout may have no .venv; the constant still has to be right."""
    assert VENV_DIR == REPO_ROOT / ".venv"


def _walks_up_three(node: ast.AST) -> bool:
    """True for ``<anything>.parent.parent.parent`` -- the chain this file bans."""
    depth = 0
    while isinstance(node, ast.Attribute) and node.attr == "parent":
        depth += 1
        node = node.value
    return depth >= 3


def test_no_module_re_derives_the_repository_root():
    """The whole point: one count, in one file, that a move cannot silently break."""
    offenders: list[str] = []
    for module in sorted(SRC.rglob("*.py")):
        if module.name == "paths.py":
            continue  # the one place the count is allowed to live
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and _walks_up_three(node):
                rel = module.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "re-derived repository root; import it from fpga_sim.paths instead: " + ", ".join(offenders)
    )
