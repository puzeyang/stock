"""Market Regime v5.1 — Slice 2: Canonical Raw Features.

Per implementation plan §4.2 (corrected per Message[162] item 2): this module
owns exactly the manifest's 8 `role: raw` fields — one canonical load per
field, reading the exact column the manifest's `field` attribute names from
the exact pinned snapshot path(s), plus a small set of DERIVED-RAW
intermediates each raw field's own `consumers` implies. It does NOT own
core/explainability/state outputs (those belong to §4.3–§4.12).

**EMPIRICAL scope decision (self-review, ChatGPT unavailable, human
consulted directly per protocol change in Message[170]):** the design marks
realized-vol estimator, price-damage construction, drawdown, and return-shock
formulas as EMPIRICAL (§17.7, §5.2) — no concrete formula is CLOSED anywhere
in the design document. Per the human's explicit direction, this module
builds the real raw-series LOADER (real CSV data, real dtypes, real
date-indexing, real point-in-time discipline) and defines the derived-feature
INTERFACE as an injectable, unimplemented parameter — it does NOT hardcode a
specific realized-volatility/price-damage formula. Choosing a concrete
estimator is a separate EMPIRICAL decision for a later slice/round, not part
of "load the raw series and expose the primitive shape." This mirrors the
plan's own rule against inventing production constants (design §0: "EMPIRICAL
values MUST NOT be presented as final constants").

**Real-data findings from loading against the actual pinned snapshots (self-
review, no second reviewer available):**
1. `BAMLH0A0HYM2.csv` (OAS) has real blank-value rows (e.g. 2023-12-25) —
   FRED's own genuine non-publication gaps, not file corruption. A blank
   value is a real MISSING observation for that date, not a load error; the
   loader skips such rows (no observation recorded for that date) rather
   than treating the whole file as malformed.
2. `BREADTH_V5_1` declares NINE snapshot paths (the fixed nine-sector ETF
   universe, design §3.3 Tier 2), not one — confirmed by reading the live
   manifest. The manifest itself declares `breadth_member_observations` as
   `data_type: "array", shape: "collection"`, not a scalar series like the
   other 7 raw fields. A single-series `RawSeries` type is therefore the
   wrong shape for this field; `RawSeriesCollection` (below) loads and
   exposes all nine member series keyed by their source path/ticker.
"""
from __future__ import annotations

import csv
import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .contracts import Manifest, SourceContract

REPO_ROOT = Path(__file__).resolve().parents[3]

# Manifest raw field_id -> source_contract_id, per plan §4.2's table.
RAW_FIELD_TO_CONTRACT = {
    "benchmark_total_return_close": "BENCHMARK_V5_1",
    "breadth_member_observations": "BREADTH_V5_1",
    "oas_level": "OAS_V5_1",
    "qqq_total_return_close": "QQQ_V5_1",
    "iwm_total_return_close": "IWM_V5_1",
    "vix_level": "VIX_V5_1",
    "vix9d_level": "VIX9D_V5_1",
    "vix3m_level": "VIX3M_DIAGNOSTIC_V5_1",
}
RAW_FIELD_IDS = tuple(RAW_FIELD_TO_CONTRACT.keys())

# Raw fields whose manifest entry declares a single scalar series
# (data_type: number). Everything in RAW_FIELD_IDS not in this set is a
# collection-shaped field, currently only breadth_member_observations.
SCALAR_RAW_FIELD_IDS = tuple(fid for fid in RAW_FIELD_IDS if fid != "breadth_member_observations")
COLLECTION_RAW_FIELD_IDS = ("breadth_member_observations",)

DATE_COLUMN_CANDIDATES = ("date", "observation_date")


class RawSeriesLoadError(Exception):
    """Raised on any failure to load a raw series from its pinned snapshot.
    Fails closed — never returns a partial series silently."""


@dataclass(frozen=True)
class RawObservation:
    """One (date, value) pair from a raw source series, with the identity
    metadata needed for downstream freshness/point-in-time evaluation."""

    date: str  # ISO date
    value: float
    source_contract_id: str
    field_name: str


@dataclass(frozen=True)
class RawSeries:
    """A canonical scalar raw feature's full loaded series — one per
    SCALAR_RAW_FIELD_IDS entry. Dates are sorted ascending, unique, and
    every value is a real float parsed from the pinned CSV. Rows with a
    blank/empty value are NOT included as observations (a real missing
    observation for that date, per design §4.1 — never interpolated,
    forward-filled, or defaulted); they are simply absent from
    `observations`, exactly like a date the source file never had a row for."""

    field_id: str
    source_contract_id: str
    field_name: str
    observations: tuple[RawObservation, ...]  # sorted ascending by date

    def __post_init__(self) -> None:
        dates = [o.date for o in self.observations]
        if dates != sorted(dates):
            raise RawSeriesLoadError(f"{self.field_id}: observations are not sorted ascending by date")
        if len(dates) != len(set(dates)):
            raise RawSeriesLoadError(f"{self.field_id}: observations contain duplicate dates")

    def value_on(self, date: str) -> float | None:
        """Exact-date lookup. Returns None if no observation exists for that
        date — callers must treat this as MISSING per design §4.1's
        fail-closed rule, never substitute a neighbor or a fill value."""
        for o in self.observations:
            if o.date == date:
                return o.value
        return None

    def as_of(self, date: str) -> RawObservation | None:
        """The most recent observation with date <= `date` (point-in-time
        lookup — never returns an observation strictly after `date`, per
        design §1.3's no-lookahead requirement). Returns None if no
        observation exists on or before `date`."""
        candidates = [o for o in self.observations if o.date <= date]
        if not candidates:
            return None
        return max(candidates, key=lambda o: o.date)

    def window_ending(self, date: str, size: int) -> tuple[RawObservation, ...] | None:
        """The `size` most recent observations with date <= `date`,
        ascending, ending at the observation for `date` itself if one
        exists on that exact date (or the most recent prior one otherwise).
        Returns None if fewer than `size` qualifying observations exist —
        callers must fail closed, never silently accept a shorter window."""
        candidates = [o for o in self.observations if o.date <= date]
        if len(candidates) < size:
            return None
        return tuple(candidates[-size:])


@dataclass(frozen=True)
class RawSeriesCollection:
    """A canonical collection-shaped raw feature's full loaded set of member
    series — currently only `breadth_member_observations` (design §3.3's
    fixed nine-sector Tier 2 universe). Keyed by the member's relative
    snapshot path (stable, matches the manifest's own snapshot_sha256 keys),
    not by a derived ticker symbol, so identity always traces back to the
    manifest without a second parsing step."""

    field_id: str
    source_contract_id: str
    field_name: str
    members: dict[str, RawSeries]  # relative_path -> that member's series

    def member_count(self) -> int:
        return len(self.members)

    def values_on(self, date: str) -> dict[str, float]:
        """Every member's value on `date`, for members that have one. A
        member with no observation on `date` is simply absent from the
        result — callers compute their own coverage/eligible-count logic
        from `len(result)` vs `member_count()`, per design §3.3/§6.4's
        coverage-denominator requirement; this method does not itself
        decide what counts as sufficient coverage."""
        return {
            path: v
            for path, series in self.members.items()
            if (v := series.value_on(date)) is not None
        }


def _find_date_column(header: list[str]) -> int:
    for candidate in DATE_COLUMN_CANDIDATES:
        if candidate in header:
            return header.index(candidate)
    raise RawSeriesLoadError(f"no recognized date column in header {header} (expected one of {DATE_COLUMN_CANDIDATES})")


def _load_csv_column(path: Path, value_column: str) -> list[tuple[str, float]]:
    """Load (date, value) pairs from one CSV column. A row whose value cell
    is blank/empty is skipped (a real missing observation for that date),
    not treated as a load error — confirmed against real pinned data
    (BAMLH0A0HYM2.csv has genuine blank rows on FRED non-publication dates).
    A row whose value cell is present but non-numeric IS a load error — that
    is genuine file corruption, not a natural gap."""
    if not path.exists():
        raise RawSeriesLoadError(f"raw series source file does not exist: {path}")

    pairs: list[tuple[str, float]] = []
    with path.open() as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise RawSeriesLoadError(f"{path} is empty (no header row)")
        date_idx = _find_date_column(header)
        if value_column not in header:
            raise RawSeriesLoadError(f"{path} has no column {value_column!r} (header: {header})")
        value_idx = header.index(value_column)

        for row_num, row in enumerate(reader, start=2):
            if len(row) <= max(date_idx, value_idx):
                raise RawSeriesLoadError(f"{path}:{row_num}: row too short for declared columns: {row!r}")
            date_str = row[date_idx]
            try:
                datetime.date.fromisoformat(date_str)
            except ValueError as exc:
                raise RawSeriesLoadError(f"{path}:{row_num}: invalid ISO date {date_str!r}: {exc}") from exc

            raw_value = row[value_idx].strip()
            if raw_value == "":
                continue  # real missing observation for this date, not a load error
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise RawSeriesLoadError(f"{path}:{row_num}: non-numeric value {row[value_idx]!r}: {exc}") from exc
            pairs.append((date_str, value))

    return pairs


def _build_series(field_id: str, contract_id: str, field_name: str, rel_path: str, repo_root: Path) -> RawSeries:
    abs_path = repo_root / rel_path
    pairs = _load_csv_column(abs_path, field_name)
    pairs.sort(key=lambda p: p[0])
    dates_seen: set[str] = set()
    for date_str, _ in pairs:
        if date_str in dates_seen:
            raise RawSeriesLoadError(f"{abs_path}: duplicate date {date_str!r} in source file")
        dates_seen.add(date_str)
    observations = tuple(
        RawObservation(date=d, value=v, source_contract_id=contract_id, field_name=field_name) for d, v in pairs
    )
    return RawSeries(field_id=field_id, source_contract_id=contract_id, field_name=field_name, observations=observations)


def load_raw_series(field_id: str, manifest: Manifest, repo_root: Path = REPO_ROOT) -> RawSeries:
    """Load one canonical SCALAR raw feature's full series from its pinned
    snapshot, per the manifest's own declared source contract and field
    name — never a hardcoded path or column, per plan §0's identity-
    inheritance rule. Raises ValueError if `field_id` is the collection-
    shaped `breadth_member_observations` — use `load_raw_collection` instead."""
    if field_id not in SCALAR_RAW_FIELD_IDS:
        if field_id in COLLECTION_RAW_FIELD_IDS:
            raise ValueError(f"{field_id!r} is a collection-shaped field — use load_raw_collection(), not load_raw_series()")
        raise ValueError(f"{field_id!r} is not one of the manifest's scalar raw fields: {SCALAR_RAW_FIELD_IDS}")

    contract_id = RAW_FIELD_TO_CONTRACT[field_id]
    contract: SourceContract = manifest.get_contract(contract_id)

    hash_errors = contract.verify_snapshot_hashes(repo_root)
    if hash_errors:
        raise RawSeriesLoadError(f"{field_id}: snapshot identity verification failed: {hash_errors}")

    if len(contract.snapshot_paths) != 1:
        raise RawSeriesLoadError(
            f"{field_id}: contract {contract_id} declares {len(contract.snapshot_paths)} snapshot path(s), "
            f"expected exactly 1 for a scalar raw field — if this contract legitimately needs multiple "
            f"paths, it belongs in COLLECTION_RAW_FIELD_IDS, not here"
        )

    return _build_series(field_id, contract_id, contract.field_name, contract.snapshot_paths[0], repo_root)


def load_raw_collection(field_id: str, manifest: Manifest, repo_root: Path = REPO_ROOT) -> RawSeriesCollection:
    """Load one canonical COLLECTION-shaped raw feature's full set of member
    series. Currently only `breadth_member_observations` (the fixed
    nine-sector Tier 2 universe, design §3.3)."""
    if field_id not in COLLECTION_RAW_FIELD_IDS:
        raise ValueError(f"{field_id!r} is not one of the manifest's collection raw fields: {COLLECTION_RAW_FIELD_IDS}")

    contract_id = RAW_FIELD_TO_CONTRACT[field_id]
    contract: SourceContract = manifest.get_contract(contract_id)

    hash_errors = contract.verify_snapshot_hashes(repo_root)
    if hash_errors:
        raise RawSeriesLoadError(f"{field_id}: snapshot identity verification failed: {hash_errors}")

    if not contract.snapshot_paths:
        raise RawSeriesLoadError(f"{field_id}: contract {contract_id} declares no snapshot_paths")

    members: dict[str, RawSeries] = {}
    for rel_path in contract.snapshot_paths:
        member_series = _build_series(field_id, contract_id, contract.field_name, rel_path, repo_root)
        members[rel_path] = member_series

    return RawSeriesCollection(field_id=field_id, source_contract_id=contract_id, field_name=contract.field_name, members=members)


def load_all_raw_series(manifest: Manifest, repo_root: Path = REPO_ROOT) -> dict[str, RawSeries]:
    """Load all 7 scalar canonical raw features. Fails closed on the first
    error — a partially-loaded set is never returned. Does NOT include
    breadth_member_observations — call load_raw_collection for that
    separately, since it is a different shape."""
    return {field_id: load_raw_series(field_id, manifest, repo_root) for field_id in SCALAR_RAW_FIELD_IDS}


# ---------------------------------------------------------------------------
# Derived-raw feature interface — EMPIRICAL, deliberately left unimplemented.
# ---------------------------------------------------------------------------

class DerivedRawEstimator(Protocol):
    """The shape a derived-raw feature computation (realized volatility,
    price_damage, drawdown, return_shock, rotation raw series, etc.) MUST
    have, once an EMPIRICAL formula is actually chosen in a later round.
    This module defines the interface only — it does not choose or embed
    a specific formula, per the human's explicit direction (see module
    docstring) and design §0's "EMPIRICAL values MUST NOT be presented as
    final constants" rule."""

    def __call__(self, series: RawSeries, as_of: str) -> float | None:
        """Return the derived value as of `as_of`, or None if unavailable
        (insufficient history, missing required inputs, etc.) — implementers
        MUST fail closed per design §4.1, never return a neutral/zero fill."""
        ...


# Registry of derived-raw feature names this module is RESPONSIBLE for
# eventually producing, per plan §4.2's table — deliberately mapped to no
# estimator yet. Attempting to look one up raises NotImplementedError with a
# clear message, rather than silently returning a wrong/default value.
DERIVED_RAW_FEATURE_NAMES = (
    "realized_volatility",       # from benchmark_total_return_close
    "benchmark_drawdown",        # from benchmark_total_return_close
    "benchmark_return_shock",    # from benchmark_total_return_close
    "price_damage",              # from benchmark_total_return_close (design §6.6, shared not re-derived)
    "growth_rotation_raw",       # from qqq_total_return_close + benchmark_total_return_close
    "small_cap_rotation_raw",    # from iwm_total_return_close + benchmark_total_return_close
)

_DERIVED_RAW_ESTIMATORS: dict[str, DerivedRawEstimator] = {}


def register_derived_raw_estimator(name: str, estimator: DerivedRawEstimator) -> None:
    """Inject a concrete EMPIRICAL estimator for one derived-raw feature.
    This is the explicit, visible seam the plan requires — no formula is
    embedded in this module's own code; a caller (a later slice/round) must
    call this to make a derived feature computable at all."""
    if name not in DERIVED_RAW_FEATURE_NAMES:
        raise ValueError(f"{name!r} is not a recognized derived-raw feature name: {DERIVED_RAW_FEATURE_NAMES}")
    _DERIVED_RAW_ESTIMATORS[name] = estimator


def compute_derived_raw(name: str, series: RawSeries, as_of: str) -> float | None:
    """Compute a derived-raw feature using its registered EMPIRICAL
    estimator. Raises NotImplementedError (not a silent default) if no
    estimator has been registered yet for `name` — this is deliberate: Slice
    2 defines the interface, it does not choose the formula."""
    if name not in DERIVED_RAW_FEATURE_NAMES:
        raise ValueError(f"{name!r} is not a recognized derived-raw feature name: {DERIVED_RAW_FEATURE_NAMES}")
    estimator = _DERIVED_RAW_ESTIMATORS.get(name)
    if estimator is None:
        raise NotImplementedError(
            f"no EMPIRICAL estimator registered for derived-raw feature {name!r} — "
            f"its formula is not yet decided (design §17.7/§5.2); call register_derived_raw_estimator() "
            f"to supply one once that EMPIRICAL choice is made, do not hardcode a default here"
        )
    return estimator(series, as_of)
