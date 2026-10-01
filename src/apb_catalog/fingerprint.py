"""Content fingerprints of effective APB rules, as stored in each level's ``rule_json``."""

from __future__ import annotations

import hashlib
import json

from apb2.result_facade import JsonValue


def canonical_json(value: JsonValue, /) -> str:
    """Serialize with sorted object keys and preserved array order, so equal rules hash equally."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def fingerprint(value: JsonValue, /) -> str:
    """Return the ``sha256:<hex>`` fingerprint of one JSON value."""
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
