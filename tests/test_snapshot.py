"""The published JSON Schema must describe the snapshot model this package writes."""

from __future__ import annotations

import json

from apb_catalog.fingerprint import canonical_json, fingerprint
from apb_catalog.snapshot import packaged_json_schema, snapshot_json_schema


def test_the_packaged_schema_matches_the_snapshot_model() -> None:
    """Regenerate with ``make schema`` after changing the snapshot contract."""
    assert json.loads(packaged_json_schema()) == snapshot_json_schema()


def test_canonical_json_sorts_keys_and_keeps_array_order() -> None:
    """Key order never changes a fingerprint; array order always does."""
    assert canonical_json({"b": [2, 1], "a": "é"}) == '{"a":"é","b":[2,1]}'
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})
    assert fingerprint([1, 2]) != fingerprint([2, 1])
    assert fingerprint({}).startswith("sha256:")
