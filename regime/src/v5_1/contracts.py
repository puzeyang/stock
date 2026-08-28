"""Market Regime v5.1 — Slice 1: Contracts & Primitives, module 4.1's manifest
loader half.

Per `Market_Regime_v5.1_Reference_Implementation_Plan.md` §4.1: parses
`market_regime_fields.v5.1.json` against `market_regime_field_manifest.schema.v1.0.0.json`
(jsonschema Draft 2020-12), exposing typed `SourceContract` objects with the
full §3.1 metadata required by the design (provider, symbol, field, dataset
version, source tier, timestamps/timezone/calendar/frequency, units,
adjustment/vintage policy, freshness/staleness limits, missing-data rule,
coverage denominator, warm-up requirement, duplicate/alignment policy,
polarity, monotonicity assertion, consumers).

Fails closed and loudly on any manifest/schema mismatch — this module MUST
NOT silently accept a manifest that fails schema validation, since every
downstream slice trusts this loader as the sole source of source-contract
truth (plan §0's identity-inheritance rule: every slice re-verifies
source-snapshot hashes against the live manifest at run time).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "regime/schema/market_regime_fields.v5.1.json"
DEFAULT_SCHEMA_PATH = REPO_ROOT / "regime/schema/market_regime_field_manifest.schema.v1.0.0.json"


class ManifestLoadError(Exception):
    """Raised when the manifest fails to load, parse, or validate against the
    pinned schema. Callers must treat this as fatal — there is no valid
    fallback source-contract truth."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SourceContract:
    """Typed view of one manifest `source_contracts` entry, exposing the
    design §3.1 metadata fields verbatim from the manifest — no field is
    invented or defaulted here; a manifest missing a required field fails
    schema validation upstream, not silently here."""

    source_contract_id: str
    status: str
    provider: str
    dataset: str
    symbol_or_collection: str
    field_name: str
    frequency: str
    timezone: str
    adjustment_policy: str
    vintage_policy: str
    freshness_rule: str
    missing_rule: str
    splice_policy: str
    dataset_version: str
    source_tier: str
    snapshot_paths: tuple[str, ...]
    snapshot_sha256: dict[str, str]
    refresh_policy: str
    calendar: str | None = None
    observation_timestamp_policy: str | None = None
    publication_timestamp_policy: str | None = None
    availability_lag: str | None = None
    point_in_time_join_rule: str | None = None
    price_field_policy: str | None = None
    corporate_action_policy: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def resolve_snapshot_paths(self, repo_root: Path = REPO_ROOT) -> list[tuple[str, Path]]:
        """Return (relative_path, absolute_path) pairs for every declared
        snapshot. Does not check existence — callers verify per plan §0's
        identity-inheritance rule (re-check hashes live, don't trust a
        cached assumption)."""
        return [(rel, repo_root / rel) for rel in self.snapshot_paths]

    def verify_snapshot_hashes(self, repo_root: Path = REPO_ROOT) -> list[str]:
        """Re-verify every declared snapshot's current bytes against the
        manifest's pinned hash. Returns a list of error strings; empty means
        every snapshot matches. Fails closed — a missing file or an unpinned
        hash is an error, never a silent skip."""
        errors: list[str] = []
        for rel, abs_path in self.resolve_snapshot_paths(repo_root):
            if not abs_path.exists():
                errors.append(f"{self.source_contract_id}: snapshot {rel} does not exist on disk")
                continue
            pinned = self.snapshot_sha256.get(rel)
            if not pinned:
                errors.append(f"{self.source_contract_id}: snapshot {rel} has no pinned hash in the manifest")
                continue
            actual = sha256_file(abs_path)
            if actual != pinned:
                errors.append(
                    f"{self.source_contract_id}: snapshot {rel} hash {actual} != pinned {pinned} "
                    f"— source has drifted from the manifest's pinned identity"
                )
        return errors


@dataclass(frozen=True)
class Manifest:
    """Typed view of the whole loaded, schema-validated manifest."""

    manifest_format_version: str
    schema_version: str
    feature_contract_version: str
    design_document: str
    design_sha256: str
    generated_at: str
    status: str
    canonical_calendar: dict[str, Any]
    source_contracts: dict[str, SourceContract]
    fields: dict[str, dict[str, Any]]
    manifest_path: Path
    manifest_sha256: str
    raw: dict[str, Any] = field(repr=False, compare=False)

    def get_contract(self, source_contract_id: str) -> SourceContract:
        try:
            return self.source_contracts[source_contract_id]
        except KeyError:
            raise KeyError(
                f"source_contract_id {source_contract_id!r} not found in manifest "
                f"(known: {sorted(self.source_contracts.keys())})"
            ) from None

    def verify_design_doc_identity(self, repo_root: Path = REPO_ROOT) -> str | None:
        """Re-check the manifest's own pinned design-doc hash against the
        real design document's current bytes. Returns an error string, or
        None if it matches."""
        design_path = repo_root / self.design_document
        if not design_path.exists():
            return f"design_document {self.design_document} referenced by manifest does not exist on disk"
        actual = sha256_file(design_path)
        if actual != self.design_sha256:
            return (
                f"design_document {self.design_document} hash {actual} != manifest's pinned "
                f"design_sha256 {self.design_sha256} — design doc has drifted from the manifest's own identity"
            )
        return None


def _extract_source_contract(raw: dict[str, Any]) -> SourceContract:
    return SourceContract(
        source_contract_id=raw["source_contract_id"],
        status=raw["status"],
        provider=raw["provider"],
        dataset=raw["dataset"],
        symbol_or_collection=raw["symbol_or_collection"],
        field_name=raw["field"],
        frequency=raw["frequency"],
        timezone=raw["timezone"],
        adjustment_policy=raw["adjustment_policy"],
        vintage_policy=raw["vintage_policy"],
        freshness_rule=raw["freshness_rule"],
        missing_rule=raw["missing_rule"],
        splice_policy=raw["splice_policy"],
        dataset_version=raw["dataset_version"],
        source_tier=raw["source_tier"],
        snapshot_paths=tuple(raw.get("snapshot_paths", [])),
        snapshot_sha256=dict(raw.get("snapshot_sha256", {})),
        refresh_policy=raw["refresh_policy"],
        calendar=raw.get("calendar"),
        observation_timestamp_policy=raw.get("observation_timestamp_policy"),
        publication_timestamp_policy=raw.get("publication_timestamp_policy"),
        availability_lag=raw.get("availability_lag"),
        point_in_time_join_rule=raw.get("point_in_time_join_rule"),
        price_field_policy=raw.get("price_field_policy"),
        corporate_action_policy=raw.get("corporate_action_policy"),
        raw=raw,
    )


def load_manifest(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> Manifest:
    """Load and schema-validate the v5.1 field manifest. Raises
    ManifestLoadError on any failure — missing file, malformed JSON, or
    schema-validation failure. Never returns a partially-valid manifest."""
    if not manifest_path.exists():
        raise ManifestLoadError(f"manifest not found: {manifest_path}")
    if not schema_path.exists():
        raise ManifestLoadError(f"manifest schema not found: {schema_path}")

    try:
        with manifest_path.open() as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        raise ManifestLoadError(f"manifest {manifest_path} is not valid JSON: {exc}") from exc

    try:
        with schema_path.open() as f:
            schema = json.load(f)
    except json.JSONDecodeError as exc:
        raise ManifestLoadError(f"schema {schema_path} is not valid JSON: {exc}") from exc

    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
    if errors:
        formatted = "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:10])
        raise ManifestLoadError(f"manifest failed schema validation ({len(errors)} error(s)): {formatted}")

    contracts: dict[str, SourceContract] = {}
    for c in raw.get("source_contracts", []):
        sc = _extract_source_contract(c)
        if sc.source_contract_id in contracts:
            raise ManifestLoadError(f"duplicate source_contract_id in manifest: {sc.source_contract_id}")
        contracts[sc.source_contract_id] = sc

    fields: dict[str, dict[str, Any]] = {}
    for f in raw.get("fields", []):
        fid = f.get("field_id")
        if not fid:
            raise ManifestLoadError(f"manifest field missing field_id: {f!r}")
        if fid in fields:
            raise ManifestLoadError(f"duplicate field_id in manifest: {fid}")
        fields[fid] = f

    return Manifest(
        manifest_format_version=raw["manifest_format_version"],
        schema_version=raw["schema_version"],
        feature_contract_version=raw["feature_contract_version"],
        design_document=raw["design_document"],
        design_sha256=raw["design_sha256"],
        generated_at=raw["generated_at"],
        status=raw["status"],
        canonical_calendar=raw["canonical_calendar"],
        source_contracts=contracts,
        fields=fields,
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
        raw=raw,
    )
