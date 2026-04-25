"""Tests for SevenSegDef and BoardDef JSON round-trip serialization."""

import pytest

from fpga_sim.board_loader import BoardDef, SevenSegDef


def test_roundtrip_with_sevenseg():
    ssd = SevenSegDef(6, False, False, True, False)
    bd = BoardDef(name="Test", class_name="TestPlatform", seven_seg=ssd)
    assert BoardDef.from_json(bd.to_json()).seven_seg == ssd


def test_roundtrip_without_sevenseg():
    bd = BoardDef(name="Test", class_name="TestPlatform")
    assert BoardDef.from_json(bd.to_json()).seven_seg is None


def test_roundtrip_preserves_all_fields():
    ssd = SevenSegDef(8, True, True, False, True)
    bd = BoardDef(name="Nexys4", class_name="Nexys4DDRPlatform", seven_seg=ssd)
    restored = BoardDef.from_json(bd.to_json())
    assert restored.name == "Nexys4"
    assert restored.seven_seg == ssd


@pytest.mark.parametrize(
    "num_digits,has_dp,is_mux,inv,sel_inv",
    [
        (4, True, False, True, False),
        (8, True, True, False, True),
        (2, False, False, False, False),
        (6, False, False, True, False),
    ],
)
def test_sevensegdef_dict_roundtrip(num_digits, has_dp, is_mux, inv, sel_inv):
    ssd = SevenSegDef(num_digits, has_dp, is_mux, inv, sel_inv)
    assert SevenSegDef.from_dict(ssd.to_dict()) == ssd


def test_from_dict_missing_required_field_raises():
    with pytest.raises(KeyError):
        SevenSegDef.from_dict({"has_dp": True, "is_multiplexed": False})


def test_from_dict_optional_fields_default():
    d = {"num_digits": 4, "has_dp": True, "is_multiplexed": False}
    ssd = SevenSegDef.from_dict(d)
    assert ssd.inverted is False
    assert ssd.select_inverted is False


def test_seven_seg_none_serializes_as_null():
    import json

    bd = BoardDef(name="Test", class_name="TestPlatform")
    data = json.loads(bd.to_json())
    assert data["seven_seg"] is None


def test_seven_seg_present_serializes_correctly():
    import json

    ssd = SevenSegDef(4, True, False, True, False)
    bd = BoardDef(name="Test", class_name="TestPlatform", seven_seg=ssd)
    data = json.loads(bd.to_json())
    assert data["seven_seg"]["num_digits"] == 4
    assert data["seven_seg"]["has_dp"] is True
    assert data["seven_seg"]["is_multiplexed"] is False
    assert data["seven_seg"]["inverted"] is True
    assert data["seven_seg"]["select_inverted"] is False
