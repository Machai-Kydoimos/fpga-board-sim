"""The hand-authored registry TOMLs conform to their JSON Schemas.

``scripts/check_registry_schema.py`` is chained from ``sync_port_conventions.py``,
but that path needs the network. These run it offline so a malformed registry
fails on the ordinary test job, on every PR, in about a millisecond.

The failure this guards is quiet, not loud: every registry field is read with
``.get()``, so a typo'd key never raises -- it reads as absent and changes what
a sync run does. ``fetchd = true`` skips the row for "not fetched",
``status = "verifed"`` never verifies, ``format = "QFS"`` finds no parser. The
run stays green and simply does less, which is the silent-skip shape #335
closed for dead citations and this closes for malformed ones.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from check_registry_schema import LCS_DIR, PCS_DIR, check_cross_field, check_schemas, maker_files

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

PROJECT = Path(__file__).resolve().parent.parent


def test_every_registry_toml_matches_its_schema() -> None:
    assert check_schemas() == []


def test_registry_cross_field_rules_hold() -> None:
    # Consecutive ranks, unique row names, files[] resolving to real board JSONs,
    # and every overlay/waves entry naming a real row.
    assert check_cross_field() == []


def test_every_registry_file_is_covered_by_a_schema() -> None:
    # A new TOML dropped into either directory must be validated, not silently
    # ignored -- that would reintroduce exactly the blind spot this closes.
    covered = set(maker_files()) | {PCS_DIR / "overlay.toml", PCS_DIR / "waves.toml"}
    covered |= set(LCS_DIR.glob("*.toml"))
    on_disk = set(PCS_DIR.glob("*.toml")) | set(LCS_DIR.glob("*.toml"))
    assert on_disk - covered == set()


@pytest.mark.parametrize(
    "schema_path",
    [
        PCS_DIR / "registry.schema.json",
        PCS_DIR / "overlay.schema.json",
        PCS_DIR / "waves.schema.json",
        LCS_DIR / "registry.schema.json",
    ],
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_schema_files_are_strict(schema_path: Path) -> None:
    # additionalProperties:false is what turns a typo into an error instead of a
    # silently-ignored key, so assert it survives future edits to these schemas.
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def objects(node: object) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                found.append(node)
            for v in node.values():
                found += objects(v)
        elif isinstance(node, list):
            for v in node:
                found += objects(v)
        return found

    lax = [o for o in objects(schema) if o.get("additionalProperties") is not False]
    assert not lax, f"{schema_path.name}: {len(lax)} object schema(s) allow unknown keys"


def test_a_typod_key_is_rejected(tmp_path: Path) -> None:
    # The motivating case, asserted end to end rather than by inspection.
    import jsonschema

    schema = json.loads((PCS_DIR / "registry.schema.json").read_text(encoding="utf-8"))
    good = tomllib.loads((PCS_DIR / "terasic.toml").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(good)) == []

    good["board"][0]["source"][0]["fetchd"] = good["board"][0]["source"][0].pop("fetched")
    assert list(validator.iter_errors(good)), "a misspelled `fetched` must not validate"
