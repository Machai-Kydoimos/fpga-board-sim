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
