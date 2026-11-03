"""Write src/apb_catalog/data/versions.csv from APB2's packaged rules.

The catalog reads APB2's parse rules only when it is written; at runtime it reads this table:
each software version range APB2 has a rule for, its label, which entries name, and the rule's
version pattern, which a converted result stores. Run ``make versions`` after an APB2 rule
change; ``tests/test_versions.py`` fails until the table matches.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import cast

from apb2.api import packaged_rule_declarations

from apb_catalog.rules import COLUMNS

TABLE = Path(__file__).resolve().parents[1] / "src" / "apb_catalog" / "data" / "versions.csv"

VERSION_LABELS: dict[str, str] = {
    "^2\\.": "2.x",
    "^2\\..*": "2.x",
    "^1\\.": "1.x",
    "^1\\..*": "1.x",
    "^v?1\\..*": "1.x",
    "^0\\.": "0.x",
    "^0\\.5\\.": "0.5",
    "^.*$": "any",
    "^13(?:\\.|\\s|$)": "13",
    "^1\\.[0-7](\\.|$)": "1.0\u20131.7",
    "^1\\.[89](\\.|$)": "1.8\u20131.9",
    "^1\\.10(?:\\.|-|$)": "1.10",
    "^1\\.12(?:\\.|-|$)": "1.12",
    "^2[23]\\.": "22\u201323",
    "^(1\\.5|1\\.6|2\\.)": "1.5, 1.6, 2.x",
    "^(19|20)\\..*": "19\u201320",
    "^15\\..*": "15",
    "^21\\..*": "21",
    "^0\\.9\\.11$": "0.9.11",
}
"""Concise readings of the rules' version patterns; a new pattern needs a label here."""


def render() -> str:
    """The table's text: one row per software version range, in APB2's order.

    Raises:
        KeyError: A rule's version pattern has no label in ``VERSION_LABELS``.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    written: set[tuple[str, str]] = set()
    for texts in packaged_rule_declarations().values():
        declared = cast(dict[str, object], json.loads(texts[0]))
        software, pattern = (
            str(declared["software_name"]),
            str(declared["software_version_pattern"]),
        )
        if pattern not in VERSION_LABELS:
            raise KeyError(f"no version label for {pattern!r}; add one to VERSION_LABELS")
        if (software, pattern) not in written:
            written.add((software, pattern))
            writer.writerow((software, VERSION_LABELS[pattern], pattern))
    return buffer.getvalue()


if __name__ == "__main__":
    TABLE.write_text(render(), encoding="utf-8")
    print(f"wrote {TABLE}")
