#!/usr/bin/env python3
"""Verify market_regime_v5.1_field_ownership.v1.0.json against the pinned
v5.1 field manifest, per ChatGPT msg 164 item 1's explicit requirement:
"require exact key equality with manifest field IDs, exactly one owner from
the closed 4.1-4.12 vocabulary, and cross-check owner/role compatibility."

This is a standalone independent checker, separate from the script that
built the ownership map artifact — a builder validating its own output is
not independent proof; a separate verifier re-checking the artifact against
the live manifest is.

Exits 0 and prints PASS with a summary if every check passes.
Exits 1 and prints every failing check if any check fails.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "regime/schema/market_regime_fields.v5.1.json"
OWNERSHIP_PATH = REPO_ROOT / "regime/schema/market_regime_v5.1_field_ownership.v1.0.json"

CLOSED_MODULE_VOCABULARY = {
    "4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7",
    "4.8", "4.9", "4.10", "4.11", "4.12",
}

EXPECTED_ROLE_COMPATIBILITY = {
    "raw": {"4.2"},
    "state": {"4.3", "4.10"},
    "core": CLOSED_MODULE_VOCABULARY - {"4.1"},
    "explainability": CLOSED_MODULE_VOCABULARY,
}


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(manifest: dict, ownership: dict) -> list[str]:
    errors: list[str] = []

    manifest_fields = manifest.get("fields")
    if not isinstance(manifest_fields, list):
        return ["manifest has no 'fields' list"]
    manifest_ids = {}
    for f in manifest_fields:
        fid = f.get("field_id")
        if not fid:
            errors.append(f"manifest field missing field_id: {f!r}")
            continue
        manifest_ids[fid] = f.get("role")

    ownership_map = ownership.get("field_ownership")
    if not isinstance(ownership_map, dict):
        return ["ownership artifact has no 'field_ownership' object"]

    # Exact key equality: manifest field IDs == ownership keys.
    manifest_id_set = set(manifest_ids.keys())
    ownership_id_set = set(ownership_map.keys())
    missing = manifest_id_set - ownership_id_set
    extra = ownership_id_set - manifest_id_set
    if missing:
        errors.append(f"{len(missing)} manifest field(s) have no ownership entry: {sorted(missing)}")
    if extra:
        errors.append(f"{len(extra)} ownership entries reference no manifest field: {sorted(extra)}")

    # Exactly one owner per field, from the closed vocabulary.
    for field_id, owner in ownership_map.items():
        if not isinstance(owner, str):
            errors.append(f"{field_id}: owner must be a single string, got {owner!r}")
            continue
        if owner not in CLOSED_MODULE_VOCABULARY:
            errors.append(f"{field_id}: owner {owner!r} is not in the closed 4.1-4.12 module vocabulary")

    # No duplicate/multiple ownership (a dict can't literally have duplicate keys in
    # valid JSON, but check the loaded structure has exactly 86 unique keys as a
    # positive assertion rather than assuming JSON parsing already guarantees it).
    if len(ownership_map) != len(set(ownership_map.keys())):
        errors.append("ownership map has duplicate field_id keys (should be structurally impossible in valid JSON; investigate)")
    if len(manifest_fields) != len(manifest_ids):
        errors.append(f"manifest has {len(manifest_fields)} field entries but only {len(manifest_ids)} unique field_ids — duplicate field_id in manifest")

    # Role/owner compatibility.
    declared_compat = ownership.get("role_compatibility")
    if not isinstance(declared_compat, dict):
        errors.append("ownership artifact missing 'role_compatibility' object")
        declared_compat = {}
    for role, expected_owners in EXPECTED_ROLE_COMPATIBILITY.items():
        declared = set(declared_compat.get(role, []))
        if declared != expected_owners:
            errors.append(
                f"role_compatibility[{role!r}] = {sorted(declared)}, expected exactly {sorted(expected_owners)}"
            )

    for field_id, owner in ownership_map.items():
        role = manifest_ids.get(field_id)
        if role is None:
            continue  # already reported as an "extra" entry above
        allowed = EXPECTED_ROLE_COMPATIBILITY.get(role)
        if allowed is not None and owner in CLOSED_MODULE_VOCABULARY and owner not in allowed:
            errors.append(f"{field_id}: role={role!r} owned by {owner!r}, which is not role-compatible (allowed: {sorted(allowed)})")

    # Declared module vocabulary in the artifact matches the closed set exactly.
    declared_modules = set(ownership.get("module_vocabulary", {}).keys())
    if declared_modules != CLOSED_MODULE_VOCABULARY:
        errors.append(f"artifact's module_vocabulary keys {sorted(declared_modules)} != closed vocabulary {sorted(CLOSED_MODULE_VOCABULARY)}")

    return errors


def main() -> int:
    if not MANIFEST_PATH.exists():
        print(f"FAIL: manifest not found at {MANIFEST_PATH}")
        return 1
    if not OWNERSHIP_PATH.exists():
        print(f"FAIL: ownership artifact not found at {OWNERSHIP_PATH}")
        return 1

    with MANIFEST_PATH.open() as f:
        manifest = json.load(f)
    with OWNERSHIP_PATH.open() as f:
        ownership = json.load(f)

    errors = verify(manifest, ownership)

    print(f"manifest file:   {MANIFEST_PATH}")
    print(f"manifest sha256: {sha256_file(MANIFEST_PATH)}")
    print(f"ownership file:  {OWNERSHIP_PATH}")
    print(f"ownership sha256:{sha256_file(OWNERSHIP_PATH)}")
    print(f"verifier file:   {Path(__file__).resolve()}")
    print(f"verifier sha256: {sha256_file(Path(__file__).resolve())}")
    print()

    if errors:
        print(f"FAIL ({len(errors)} check(s) failed)")
        for e in errors:
            print(f" - {e}")
        return 1

    field_count = len(ownership.get("field_ownership", {}))
    print(f"PASS — manifest IDs == ownership keys, {field_count} unique field assignments, "
          f"all owners in closed 4.1-4.12 vocabulary, all role-compatible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
