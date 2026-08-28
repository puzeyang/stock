#!/usr/bin/env python3
"""Validate a Market Regime output record against the canonical field manifest."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


TYPE_CHECKS = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
    "boolean": lambda value: isinstance(value, bool),
    "timestamp": lambda value: isinstance(value, str),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
}


def validate_record(manifest: dict[str, Any], record: dict[str, Any]) -> list[str]:
    fields = {row["field_id"]: row for row in manifest["fields"]}
    errors: list[str] = []
    for unknown in sorted(set(record) - set(fields)):
        errors.append(f"{unknown}: undeclared field")
    for field_id, row in fields.items():
        if not row["nullable"] and field_id not in record:
            errors.append(f"{field_id}: required non-nullable field is missing")
            continue
        if field_id not in record:
            continue
        value = record[field_id]
        if value is None:
            if not row["nullable"]:
                errors.append(f"{field_id}: null violates nullability")
            continue
        check = TYPE_CHECKS[row["data_type"]]
        if not check(value):
            errors.append(f"{field_id}: value violates data_type={row['data_type']}")
            continue
        domain = row["range"]
        if "enum" in domain and value not in domain["enum"]:
            errors.append(f"{field_id}: value is outside enum {domain['enum']}")
        if "minimum" in domain and domain["minimum"] is not None and value < domain["minimum"]:
            errors.append(f"{field_id}: value is below minimum {domain['minimum']}")
        if "maximum" in domain and domain["maximum"] is not None and value > domain["maximum"]:
            errors.append(f"{field_id}: value is above maximum {domain['maximum']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    record = json.loads(args.record.read_text())
    errors = validate_record(manifest, record)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
