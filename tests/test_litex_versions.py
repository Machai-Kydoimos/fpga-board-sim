"""Every version a LiteX platform file lists becomes a board (U56 Phase 7, plan §4.7, D-4).

The detector reads upstream's syntax tree and runs nothing (D-7); each version it finds
is built by the same reader as the default and named by the identity rules (§4.1).
Hermetic: inline platform files, the real reader and the real write path, no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from litex_parser import listed_versions, read_litex_file, version_args
from sync_identity import SyncReport, run_sync
from sync_litex_boards import make_reader

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "boards" / "schema" / "board.schema.json"


def _platform(init: str, prelude: str = "") -> str:
    """A minimal LiteX platform file whose constructor body is *init*."""
    return (
        "from litex.build.generic_platform import *\n"
        "from litex.build.xilinx import Xilinx7SeriesPlatform\n\n"
        '_io = [("clk100", 0, Pins("E3")), ("user_led", 0, Pins("H5"))]\n'
        f"{prelude}\n"
        "class Platform(Xilinx7SeriesPlatform):\n"
        '    default_clk_name = "clk100"\n'
        "    default_clk_period = 1e9/100e6\n"
        f"{init}"
    )


# ── what counts as upstream listing a version (§4.7) ─────────────────────────────


def test_a_dict_literal_indexed_by_the_parameter_lists_its_keys():
    source = _platform(
        '    def __init__(self, variant="a7-35"):\n'
        '        device = {"a7-35": "xc7a35t", "a7-100": "xc7a100t"}[variant]\n'
        "        Xilinx7SeriesPlatform.__init__(self, device, _io)\n"
    )
    assert listed_versions(source, "Platform") == {"variant": ["a7-35", "a7-100"]}


def test_a_module_level_dict_lists_its_keys_too():
    # Tang's docks[dock]: the dict is bound at module level.
    source = _platform(
        '    def __init__(self, dock="standard"):\n'
        "        Xilinx7SeriesPlatform.__init__(self, 'gw', _io + _docks[dock])\n",
        prelude='_docks = {"standard": [], "lite": []}\n',
    )
    assert listed_versions(source, "Platform") == {"dock": ["standard", "lite"]}


def test_equality_and_in_lists_list_their_values():
    # Machdyne Schoko: "v2" appears only in the assert, as the else branch.
    source = _platform(
        '    def __init__(self, revision="v1", expansion="debug"):\n'
        '        assert revision in ["v1", "v2"]\n'
        '        if revision == "v1": pass\n'
        '        if expansion == "sbus": pass\n'
        "        Xilinx7SeriesPlatform.__init__(self, 'x', _io)\n"
    )
    assert listed_versions(source, "Platform") == {
        "revision": ["v1", "v2"],
        "expansion": ["sbus"],
    }


def test_a_board_setting_is_not_a_version():
    # Decided 2026-11-02: a jumper voltage is a setting of one board, not another board.
    source = _platform(
        '    def __init__(self, vccio="3.3V", toolchain="vivado"):\n'
        '        assert vccio in ["2.5V", "3.3V"]\n'
        '        assert toolchain in ["vivado", "symbiflow"]\n'
        "        Xilinx7SeriesPlatform.__init__(self, 'x', _io)\n"
    )
    assert listed_versions(source, "Platform") == {}


def test_a_listed_part_size_is_a_version_and_a_free_form_part_is_not():
    # Decided 2026-11-02: device and kgates join the version parameters.
    listed = _platform(
        '    def __init__(self, device="45F", kgates=75):\n'
        '        assert device in ["12F", "45F"]\n'
        "        assert kgates in [35, 75]\n"
        "        Xilinx7SeriesPlatform.__init__(self, device, _io)\n"
    )
    assert listed_versions(listed, "Platform") == {"device": ["12F", "45F"], "kgates": [35, 75]}
    free = _platform(
        '    def __init__(self, device="xc7a35t"):\n'
        "        Xilinx7SeriesPlatform.__init__(self, device, _io)\n"
    )
    assert listed_versions(free, "Platform") == {}


def test_an_inherited_constructor_is_read_and_bools_are_not_values():
    source = _platform(
        "    pass\n",
        prelude=(
            "class _Base(Xilinx7SeriesPlatform):\n"
            '    def __init__(self, revision="a", board=None):\n'
            '        if revision == "b" or revision == True or board == None: pass\n'
            "        Xilinx7SeriesPlatform.__init__(self, 'x', _io)\n"
        ),
    ).replace("class Platform(Xilinx7SeriesPlatform):", "class Platform(_Base):")
    assert listed_versions(source, "Platform") == {"revision": ["b"]}


def test_versions_are_built_one_parameter_at_a_time_never_the_default():
    source = _platform(
        '    def __init__(self, variant="a", revision="1"):\n'
        '        assert variant in ["a", "b"]\n'
        '        assert revision in ["1", "2", "3"]\n'
        "        Xilinx7SeriesPlatform.__init__(self, 'x', _io)\n"
    )
    outcome = read_litex_file(source, "kit.py")
    assert version_args("kit.py", source, outcome) == [
        {"variant": "b"},
        {"revision": "2"},
        {"revision": "3"},
    ]


# ── the write path ───────────────────────────────────────────────────────────────

_KIT = _platform(
    '    def __init__(self, variant="a7-35", dock="standard", revision="1", toolchain="vivado"):\n'
    '        assert revision in ["1", "2"]\n'
    '        if revision == "2" and variant != "a7-100":\n'
    '            raise ValueError("revision 2 exists only for the a7-100")\n'
    '        if variant == "35t":  # an alias of the default\n'
    '            variant = "a7-35"\n'
    "        self.variant = variant\n"
    '        device = {"a7-35": "xc7a35t", "a7-100": "xc7a100t",'
    ' "a7-100+": "xc7a100t-2"}[variant]\n'
    "        Xilinx7SeriesPlatform.__init__(self, device, _io + _docks[dock],"
    " toolchain=toolchain)\n",
    prelude='_docks = {"standard": [("user_led", 1, Pins("J5"))], "bare": []}\n',
)


def _sync(folder: Path) -> SyncReport:
    return run_sync(
        origin="litex-boards",
        repo="example/litex-boards",
        files={"kit.py": _KIT},
        commit_sha="c0ffee",
        output_dir=folder,
        read=make_reader("c0ffee", timestamp="2026-11-02T00:00:00+00:00"),
        accept_list=[],
        schema_path=SCHEMA,
        color_registry={},
        versions=version_args,
    )


def _load(folder: Path, name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((folder / name).read_text(encoding="utf-8"))
    return data


def test_every_listed_version_becomes_a_board_named_by_its_version(tmp_path):
    folder = tmp_path / "litex-boards"
    report = _sync(folder)
    assert report.new == [
        "kit.json",
        "kit_dock-bare.json",
        "kit_variant-a7-100.json",
        "kit_variant-a7-100plus.json",
    ]
    assert _load(folder, "kit.json")["source"]["upstream_args"] == {
        "variant": "a7-35",
        "dock": "standard",
        "revision": "1",
    }
    bare = _load(folder, "kit_dock-bare.json")
    assert len(bare["leds"]) == 1 and len(_load(folder, "kit.json")["leds"]) == 2
    assert bare["class_name"] == "KitDockbarePlatform"
    assert bare["name"] == "Kit (dock bare)"
    assert _load(folder, "kit_variant-a7-100.json")["device"] == "xc7a100t"


def test_a_plus_is_spelled_plus_in_names_and_kept_in_the_display_name(tmp_path):
    # Dropped, "a7-100+" would be named after the other variant, "a7-100".
    folder = tmp_path / "litex-boards"
    _sync(folder)
    plus = _load(folder, "kit_variant-a7-100plus.json")
    assert plus["class_name"] == "KitVarianta7100plusPlatform"
    assert plus["name"] == "Kit (variant a7-100+)"
    assert plus["source"]["upstream_args"]["variant"] == "a7-100+"


def test_a_version_upstream_refuses_is_a_warning_and_an_alias_is_no_second_board(tmp_path):
    folder = tmp_path / "litex-boards"
    report = _sync(folder)
    # revision 2 exists only for the a7-100: the file still reads, and the ledger says so.
    assert report.ledger["kit.py"].startswith("boards: ")
    meta = _load(folder, "_sync_metadata.json")
    assert meta["warnings"] == {"kit.py": ['version_unbuilt: {"revision": "2"}: ValueError']}
    # "35t" resolves to the default's identity: the same board, so no file of its own.
    assert sorted(p.name for p in folder.glob("kit*.json")) == [
        "kit.json",
        "kit_dock-bare.json",
        "kit_variant-a7-100.json",
        "kit_variant-a7-100plus.json",
    ]


def test_a_second_sync_rewrites_nothing(tmp_path):
    # What the drift job requires: each version pairs with its own file again.
    folder = tmp_path / "litex-boards"
    _sync(folder)
    snapshot = {p.name: p.read_bytes() for p in folder.glob("*.json")}
    report = _sync(folder)
    assert report.new == [] and report.orphans == []
    assert {p.name: p.read_bytes() for p in folder.glob("*.json")} == snapshot
