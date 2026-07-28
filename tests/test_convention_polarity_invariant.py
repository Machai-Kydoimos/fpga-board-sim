"""Fleet data invariants for framework-vs-canonical polarity (F2) and the rgb survey.

``reconcile_framework_polarity`` makes a framework-derived bank inherit a cited
canonical block's ``active_low`` (canonical is the physical truth).  These sweep
the committed board JSONs so a future re-sync or a hand-added canonical block
can't reintroduce a disagreement -- the review found exactly four such boards
(de0_cv, litefury, nitefury_ii, sipeed_tang_nano_9k), and this must stay empty.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest
from framework_conventions import _bank_width

PROJECT = Path(__file__).resolve().parent.parent
_ROLES = ("leds", "leds_green", "switches", "buttons")


def _board_files() -> list[str]:
    return [
        f
        for f in glob.glob(str(PROJECT / "boards" / "**" / "*.json"), recursive=True)
        if "schema" not in f and "_sync_metadata" not in f
    ]


def test_no_framework_bank_contradicts_canonical_polarity() -> None:
    disagreements: list[str] = []
    for f in _board_files():
        pc = json.loads(Path(f).read_text()).get("port_conventions")
        if not isinstance(pc, dict):
            continue
        canonical = [
            b
            for b in pc.values()
            if isinstance(b, dict) and b.get("naming", "canonical") == "canonical"
        ]
        if not canonical:
            continue
        for maker, block in pc.items():
            if not (isinstance(block, dict) and block.get("naming") == "framework-derived"):
                continue
            for role in _ROLES:
                fbank = block.get(role)
                if not isinstance(fbank, dict):
                    continue
                fwidth = _bank_width(fbank)
                for cblock in canonical:
                    cbank = cblock.get(role)
                    if isinstance(cbank, dict) and _bank_width(cbank) == fwidth:
                        if bool(fbank.get("active_low", False)) != bool(
                            cbank.get("active_low", False)
                        ):
                            disagreements.append(f"{Path(f).name}:{maker}:{role}(w={fwidth})")
                        break
    assert not disagreements, (
        "framework-derived banks disagree with a same-width canonical bank on "
        f"polarity (reconcile should have fixed these): {disagreements}"
    )


def test_de0_cv_framework_led_inherits_active_high_canonical() -> None:
    # Upstream amaranth de0_cv.py marks LEDs invert=True, but the DE0-CV LEDR are
    # active-high (cited terasic canonical block); the framework bank inherits that.
    fw = json.loads((PROJECT / "boards/amaranth-boards/de0_cv.json").read_text())
    assert fw["port_conventions"]["amaranth"]["leds"].get("active_low", False) is False


def test_tang_nano_9k_framework_led_inherits_active_low_canonical() -> None:
    d = json.loads((PROJECT / "boards/litex-boards/sipeed_tang_nano_9k.json").read_text())
    assert d["port_conventions"]["litex"]["leds"]["active_low"] is True


def test_atum_a3_nano_framework_led_inherits_active_low_canonical() -> None:
    # Agilex-family LEDs are active-low (Atum A3 Nano user manual: "driving its
    # associated pin to a 'low' logic level turn the LED 'on'"), same as its
    # DE23-Lite / DE25-Standard siblings -- the litex bank inherits that.
    d = json.loads((PROJECT / "boards/litex-boards/terasic_atum_a3_nano.json").read_text())
    assert d["port_conventions"]["litex"]["leds"]["active_low"] is True


# The canonical clock name, LED bank name and LED polarity for every Terasic board
# whose conventions were derived from its vendor System CD (2026-07-28).  These are
# the facts a re-sync or a hand edit could quietly undo, and two of them are traps:
# DE10-Nano's clock is FPGA_CLK1_50, *not* the CLOCK_50 every other DE board uses,
# and the "Nano" boards' LEDs are named LED, not LEDR.
_CD_CITED_TERASIC: tuple[tuple[str, str, str, bool], ...] = (
    ("amaranth-boards/de10_nano.json", "FPGA_CLK1_50", "LED", False),
    ("litex-boards/terasic_de10nano.json", "FPGA_CLK1_50", "LED", False),
    ("litex-boards/terasic_sockit.json", "OSC_50_B3B", "LED", False),
    ("custom/veek_mt_sockit.json", "OSC_50_B3B", "LED", False),
    ("litex-boards/terasic_atum_a3_nano.json", "CLOCK0_50", "LED", True),
    ("custom/de23_lite.json", "CLOCK0_50", "LEDR", True),
    ("custom/de25_standard.json", "CLOCK0_50", "LEDR", True),
    ("custom/veek_mt2.json", "CLOCK_50", "LEDR", False),
)


@pytest.mark.parametrize(("rel", "clk", "led_name", "led_active_low"), _CD_CITED_TERASIC)
def test_cd_cited_terasic_canonical_facts(
    rel: str, clk: str, led_name: str, led_active_low: bool
) -> None:
    block = json.loads((PROJECT / "boards" / rel).read_text())["port_conventions"]["terasic"]
    assert block["clk"] == clk
    assert block["leds"]["name"] == led_name
    assert bool(block["leds"].get("active_low", False)) is led_active_low
    # Terasic KEY/BUTTON pushbuttons are active-low family-wide (every user manual
    # states it in prose; DE10-Lite is cited to its CD's default design instead).
    assert block["buttons"]["active_low"] is True
    # Slide switches are active-high everywhere ("DOWN ... low logic level").
    assert "active_low" not in block["switches"]


def test_rgb_only_boards_ship_no_framework_convention() -> None:
    # A board whose only LEDs are multi-pin RGB has no single declarable LED port,
    # so it carries no framework-derived block (rgb survey -- truth over coverage).
    for rel in (
        "amaranth-boards/orange_crab_r0-1.json",
        "amaranth-boards/quickfeather.json",
        "amaranth-boards/cora_z7-10.json",
        "litex-boards/lambdaconcept_ecpix5.json",
        "litex-boards/modretro_chromatic.json",
        "litex-boards/efinix_titanium_ti60_f225_dev_kit.json",
    ):
        pc = json.loads((PROJECT / "boards" / rel).read_text()).get("port_conventions") or {}
        assert "litex" not in pc and "amaranth" not in pc, f"{rel} still has a framework block"
