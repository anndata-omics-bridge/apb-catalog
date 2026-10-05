"""The published JSON Schema must describe the snapshot model this package writes."""

from __future__ import annotations

import json

from apb_catalog.snapshot import packaged_json_schema, snapshot_json_schema


def test_the_packaged_schema_matches_the_snapshot_model() -> None:
    """Regenerate with ``make schema`` after changing the snapshot contract."""
    assert json.loads(packaged_json_schema()) == snapshot_json_schema()
