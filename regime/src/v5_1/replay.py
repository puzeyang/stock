"""Market Regime v5.1 — Slice 11: Replay Interface (module 4.13).

**This is the module the frozen Freshness Threshold Experiment actually
needs** (plan §4.13, verbatim). Given (a) a clean/ideal input dataset and
(b) the same dataset with a registered freshness injection applied (per
`freshness_injection_registry.v1.0.json`'s schema — reused directly here,
not reinvented), replay both through the full engine (`engine.py`'s
`run_engine_for_date`, wired across modules 4.1-4.12) and diff every
output field. This is what makes the freshness spec's three
engine-dependent metrics computable:

- "Affected Condition/regime bars" = fields that differ between the clean
  and injected runs (`diff_records`);
- "Delayed crisis detection" = lag between the clean run's CRISIS entry
  and the injected run's CRISIS entry, or non-entry (`crisis_entry_lag`);
- "Spurious state transitions" = state changes in the injected run absent
  from the clean run (`spurious_state_transitions`).

**Non-goal, explicitly, per the plan's own §4.13 text** (restated here
verbatim as a standing reminder, not re-derived): this replay interface
does NOT decide thresholds, does NOT touch the sealed holdout injections,
and does NOT compute portfolio outcomes — it is purely a deterministic
dual-run diff tool. **Per plan §8 item 11 / Message[158] item 1: this
module is built and tested with SYNTHETIC fixtures only in this slice. It
is NEVER applied to the real `freshness_injection_registry.v1.0.json`
registry's development or holdout injections during this build** — that
is separate, subsequent work explicitly gated on this plan's Slice 12
passing (plan §8's own item 12 framing), not concurrent with it. Nothing
in this module reads the real registry file at all.

`apply_injection` mutates a clean `RawSeriesBundle` (Slice-11/engine.py's
own bundle type) into an injected one by REMOVING observations for the
specified `contract_ids`/date range — never fabricating or altering
existing observations, since a freshness injection is defined as "this
data went missing/stale," not "this data changed value."
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .calendar import ExpectedSessionCalendar
from .contracts import Manifest
from .raw_features import RawSeries, RawSeriesCollection
from .engine import RawSeriesBundle, RunningEngineState, new_running_engine_state, run_engine_for_date, TestScaffoldingConfig, TEST_SCAFFOLDING_CONFIG


# Maps a raw-feature bundle attribute name to the SOURCE_CONTRACT_ID it
# corresponds to, per the manifest's own RAW_FIELD_TO_CONTRACT table
# (raw_features.py) — used so `apply_injection`'s caller-supplied
# `contract_ids` (matching the injection registry's own vocabulary, e.g.
# "BENCHMARK_V5_1") can be mapped onto the right RawSeriesBundle field(s)
# without the caller needing to know the bundle's internal attribute
# names.
_CONTRACT_ID_TO_BUNDLE_ATTR = {
    "BENCHMARK_V5_1": "benchmark",
    "BREADTH_V5_1": "breadth",
    "OAS_V5_1": "oas",
    "QQQ_V5_1": "qqq",
    "IWM_V5_1": "iwm",
    "VIX_V5_1": "vix",
    "VIX9D_V5_1": "vix9d",
}


def _injected_series(series: RawSeries, excluded_dates: set[str]) -> RawSeries:
    kept = tuple(o for o in series.observations if o.date not in excluded_dates)
    return replace(series, observations=kept)


def _injected_collection(collection: RawSeriesCollection, excluded_dates: set[str]) -> RawSeriesCollection:
    return replace(
        collection,
        members={path: _injected_series(member, excluded_dates) for path, member in collection.members.items()},
    )


def injection_outage_dates(calendar: ExpectedSessionCalendar, family: str, start_date: str, outage_length: int) -> tuple[str, ...]:
    """The exact set of expected-session dates an injection removes, per
    the registry's own `start_date`/`outage_length` fields: `outage_length`
    consecutive EXPECTED sessions (per the pinned calendar, not raw
    calendar days) beginning at `start_date` inclusive. Reuses the pinned
    `ExpectedSessionCalendar` artifact directly — this function does no
    calendar arithmetic of its own beyond filtering/slicing the artifact's
    own already-computed session list, per this engine's standing "reuse
    the pinned artifact, never recompute a calendar inline" discipline
    (already established in `freshness.py`).
    """
    if outage_length < 1:
        raise ValueError(f"outage_length must be >= 1, got {outage_length}")
    all_sessions = calendar.expected_sessions(family)
    from_start = [d for d in all_sessions if d >= start_date]
    if len(from_start) < outage_length:
        raise ValueError(
            f"only {len(from_start)} expected sessions on or after {start_date} for family {family!r}, "
            f"need {outage_length}"
        )
    return tuple(from_start[:outage_length])


def apply_injection(
    clean: RawSeriesBundle,
    contract_ids: tuple[str, ...],
    outage_dates: tuple[str, ...],
) -> RawSeriesBundle:
    """Return a NEW RawSeriesBundle with observations on `outage_dates`
    removed for every series/collection whose contract_id is in
    `contract_ids` — every other series is passed through UNCHANGED (the
    same object reference, since RawSeries/RawSeriesCollection are frozen
    and therefore safe to share between the clean and injected bundles
    without risk of one run's mutation leaking into the other).

    Raises ValueError for any contract_id this engine's raw-feature set
    does not recognize — fails loudly rather than silently no-op'ing an
    injection whose contract_ids don't match anything (a real risk: a
    typo'd or unsupported contract_id should never silently produce a
    'clean-and-injected are identical' result that looks like a
    zero-impact freshness injection when it was actually a no-op).
    """
    excluded_dates = set(outage_dates)
    kwargs = {}
    unrecognized = [cid for cid in contract_ids if cid not in _CONTRACT_ID_TO_BUNDLE_ATTR]
    if unrecognized:
        raise ValueError(f"apply_injection: unrecognized contract_ids {unrecognized}, expected one of {sorted(_CONTRACT_ID_TO_BUNDLE_ATTR)}")

    for contract_id, attr_name in _CONTRACT_ID_TO_BUNDLE_ATTR.items():
        current = getattr(clean, attr_name)
        if contract_id in contract_ids:
            if isinstance(current, RawSeriesCollection):
                kwargs[attr_name] = _injected_collection(current, excluded_dates)
            else:
                kwargs[attr_name] = _injected_series(current, excluded_dates)
        # else: omitted from kwargs, `replace()` keeps the clean bundle's
        # existing (unchanged, shared) value for that attribute.
    return replace(clean, **kwargs)


@dataclass(frozen=True)
class FieldDiff:
    field_id: str
    clean_value: object
    injected_value: object


@dataclass(frozen=True)
class DateDiff:
    as_of: str
    field_diffs: tuple[FieldDiff, ...]

    @property
    def has_diff(self) -> bool:
        return len(self.field_diffs) > 0


@dataclass(frozen=True)
class ReplayResult:
    """The full dual-run replay result across every as_of date in the
    run. `clean_records`/`injected_records` are keyed by as_of date, in
    the same order as `dates` — published in full (not just the diffs)
    since a caller may need the raw records for further attribution
    (per plan §4.13's "attributed to the specific injected source")."""

    dates: tuple[str, ...]
    clean_records: dict[str, dict]
    injected_records: dict[str, dict]
    date_diffs: tuple[DateDiff, ...]

    @property
    def affected_dates(self) -> tuple[str, ...]:
        """"Affected Condition/regime bars" per spec §5: every as_of date
        where at least one output field differs between the clean and
        injected runs."""
        return tuple(dd.as_of for dd in self.date_diffs if dd.has_diff)


def replay(
    dates: tuple[str, ...],
    clean_raw: RawSeriesBundle,
    injected_raw: RawSeriesBundle,
    manifest: Manifest,
    config: TestScaffoldingConfig = TEST_SCAFFOLDING_CONFIG,
) -> ReplayResult:
    """Run the full engine (via `engine.run_engine_for_date`) across
    `dates`, once against `clean_raw` and once against `injected_raw`,
    with TWO INDEPENDENT `RunningEngineState` objects (never shared —
    sharing would let one run's persisted cross-bar state leak into the
    other, corrupting the comparison), and diff every output field at
    every date.

    `dates` MUST be provided in ascending order by the caller — this
    function does not sort them itself, since persisted state (Direction
    confirmation, CRISIS/ordinary/TRENDING counters) is genuinely
    order-dependent, and silently re-sorting a caller's already-wrong
    order would mask a real caller bug rather than surface it.
    """
    clean_state = new_running_engine_state(config)
    injected_state = new_running_engine_state(config)

    clean_records: dict[str, dict] = {}
    injected_records: dict[str, dict] = {}
    date_diffs: list[DateDiff] = []

    for as_of in dates:
        clean_record = run_engine_for_date(as_of, clean_raw, clean_state, manifest, config)
        injected_record = run_engine_for_date(as_of, injected_raw, injected_state, manifest, config)
        clean_records[as_of] = clean_record
        injected_records[as_of] = injected_record
        date_diffs.append(DateDiff(as_of=as_of, field_diffs=diff_records(clean_record, injected_record)))

    return ReplayResult(dates=tuple(dates), clean_records=clean_records, injected_records=injected_records, date_diffs=tuple(date_diffs))


def diff_records(clean: dict, injected: dict) -> tuple[FieldDiff, ...]:
    """Field-by-field diff of two assembled output records. Compares the
    UNION of both records' keys (not just one side's) — a field present
    in one record but absent from the other is itself a real diff, not
    something to silently skip. Equality is exact (`!=`), matching this
    engine's deterministic-replay discipline used throughout every
    module's own test suite (`r1 == r2` for identical inputs) — no
    floating-point tolerance is applied here, since a genuinely identical
    clean-vs-injected computation on unaffected fields should be
    bit-identical, not merely close."""
    all_keys = sorted(set(clean.keys()) | set(injected.keys()))
    diffs = []
    for key in all_keys:
        clean_value = clean.get(key)
        injected_value = injected.get(key)
        if clean_value != injected_value:
            diffs.append(FieldDiff(field_id=key, clean_value=clean_value, injected_value=injected_value))
    return tuple(diffs)


def crisis_entry_lag(result: ReplayResult) -> int | None:
    """"Delayed crisis detection" per spec §5: the lag, in bars, between
    the clean run's FIRST CRISIS entry and the injected run's FIRST
    CRISIS entry.

    Returns:
    - 0 if both runs enter CRISIS on the same date;
    - a positive integer if the injected run enters CRISIS later than the
      clean run (the injection delayed detection);
    - a NEGATIVE integer if the injected run enters CRISIS EARLIER than
      the clean run (a real, distinguishable case this function does not
      collapse into "no delay" — an injection could plausibly cause an
      EARLY false CRISIS signal via a coverage/domain-count artifact, not
      only a delayed one, and the sign here preserves that distinction);
    - None if the clean run never enters CRISIS at all (no clean-run
      baseline to measure lag against) OR if the injected run never
      enters CRISIS while the clean run does (an unbounded/"non-entry"
      lag per spec §5's own "or non-entry" phrasing — represented as None
      rather than an arbitrary sentinel integer that could be mistaken
      for a real lag value).
    """
    clean_entry = _first_crisis_entry_index(result.dates, result.clean_records)
    injected_entry = _first_crisis_entry_index(result.dates, result.injected_records)
    if clean_entry is None:
        return None
    if injected_entry is None:
        return None
    return injected_entry - clean_entry


def _first_crisis_entry_index(dates: tuple[str, ...], records: dict[str, dict]) -> int | None:
    for i, d in enumerate(dates):
        if records[d].get("state") == "CRISIS":
            return i
    return None


def spurious_state_transitions(result: ReplayResult) -> tuple[str, ...]:
    """"Spurious state transitions" per spec §5: as_of dates where the
    injected run's `state` DIFFERS from the immediately preceding
    injected-run bar's `state` (i.e., a real transition happened in the
    injected run), AND the clean run shows NO transition on that same
    date (i.e., the clean run's state stayed the same across the
    corresponding two bars) — a transition the injection caused that
    would not otherwise have happened, per spec's own "absent from the
    clean run" framing.

    The first date in `dates` can never itself be a transition (there is
    no preceding bar to transition FROM) and is never included.
    """
    spurious: list[str] = []
    for i in range(1, len(result.dates)):
        prev_date, cur_date = result.dates[i - 1], result.dates[i]
        injected_transitioned = result.injected_records[cur_date].get("state") != result.injected_records[prev_date].get("state")
        clean_transitioned = result.clean_records[cur_date].get("state") != result.clean_records[prev_date].get("state")
        if injected_transitioned and not clean_transitioned:
            spurious.append(cur_date)
    return tuple(spurious)
