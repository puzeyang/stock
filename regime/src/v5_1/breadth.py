"""Market Regime v5.1 — Slice 4: Breadth (module 4.5).

Design §6.4/§3.3 (C7): participation measured independently of cap-weighted
Direction, over the pinned Tier 2 fixed-nine-sector-ETF universe (Tier 1/3
are OUT_OF_SCOPE for this reference implementation — Tier 1 requires
point-in-time constituent membership data this repo does not have, and
Tier 3 is diagnostic-only and MUST NOT auto-splice into Tier 2 per design
§3.3, so this module only ever computes against Tier 2). Source tier is
explicit in every output. Missing required coverage makes Breadth
unavailable — never neutralized (C16 fail-closed).

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`):
`pct_above_sma50`, `pct_above_sma200`, `breadth_eligible_count`,
`breadth_contribution`, `breadth_score`.

**EMPIRICAL scope (same pattern established in Slice 2, human-approved):**
design §17.4 marks the "SMA50/SMA200 participation blend and pillar weight"
EMPIRICAL — no concrete blend formula or weight is CLOSED. This module
computes the two real underlying percentages (`pct_above_sma50`,
`pct_above_sma200`) from real Tier 2 member data, and exposes their
combination into `breadth_score` as an injected `BreadthBlendConfig`
(nonnegative weights summing to one, validated at construction) — it does
not choose specific weight values.
"""
from __future__ import annotations

from dataclasses import dataclass

from .raw_features import RawSeriesCollection


class BreadthUnavailableError(Exception):
    """Not an error to catch-and-ignore — signals Breadth is genuinely
    unavailable for this as_of date per design §4.1's fail-closed rule
    (never neutralized to a default value). Callers should treat this the
    same as any other 'pillar unavailable' condition."""


@dataclass(frozen=True)
class BreadthBlendConfig:
    """EMPIRICAL (§17.4) — injected, never hardcoded. Nonnegative weights
    summing to one, combining pct_above_sma50 and pct_above_sma200 into one
    breadth_score."""

    weight_sma50: float
    weight_sma200: float

    def __post_init__(self) -> None:
        if self.weight_sma50 < 0 or self.weight_sma200 < 0:
            raise ValueError("BreadthBlendConfig weights must be nonnegative")
        total = self.weight_sma50 + self.weight_sma200
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"BreadthBlendConfig weights must sum to exactly 1.0, got {total}")


@dataclass(frozen=True)
class BreadthResult:
    """One as_of date's full Breadth computation. `source_tier` is always
    explicit per design §6.4 ("production source tier is explicit in every
    output") — this reference implementation only ever computes Tier 2, so
    it is always the literal string "tier_2_fixed_nine_production" here,
    matching the manifest's own BREADTH_V5_1.source_tier value."""

    as_of: str
    source_tier: str
    eligible_count: int
    total_members: int
    pct_above_sma50: float
    pct_above_sma200: float
    breadth_score: float


def _sma(values: list[float]) -> float:
    return sum(values) / len(values)


def compute_participation(
    collection: RawSeriesCollection,
    as_of: str,
    sma50_window: int,
    sma200_window: int,
) -> tuple[float, float, int, int]:
    """Compute (pct_above_sma50, pct_above_sma200, eligible_count,
    total_members) for the Tier 2 universe as of `as_of`.

    A member is "eligible" for a given SMA window only if it has a full
    `window`-length history ending on or before `as_of` (per §4.1's
    fail-closed rule — an under-warmed member is not silently included with
    a partial-window SMA, and is not silently excluded without affecting
    the coverage denominator design §6.4 requires). "Above" means the
    member's value as of `as_of` is strictly greater than its own SMA over
    that window.

    Raises BreadthUnavailableError if EVERY member is ineligible for a given
    window (0-of-N coverage) — a real, mid-computation "unavailable" signal,
    distinct from returning a percentage computed over zero eligible members
    (which would be a 0/0 division, not a meaningful 0%).
    """
    if sma50_window <= 0 or sma200_window <= 0:
        raise ValueError(f"SMA windows must be positive, got sma50={sma50_window}, sma200={sma200_window}")

    total_members = collection.member_count()
    if total_members == 0:
        raise BreadthUnavailableError("collection has zero members — cannot compute participation")

    above_50_count = 0
    eligible_50_count = 0
    above_200_count = 0
    eligible_200_count = 0

    for path, series in collection.members.items():
        current = series.value_on(as_of)
        if current is None:
            # Not eligible for either window if there's no observation on
            # as_of itself — a member with no bar today cannot meaningfully
            # be "above" or "below" anything today.
            continue

        w50 = series.window_ending(as_of, sma50_window)
        if w50 is not None:
            eligible_50_count += 1
            sma50 = _sma([o.value for o in w50])
            if current > sma50:
                above_50_count += 1

        w200 = series.window_ending(as_of, sma200_window)
        if w200 is not None:
            eligible_200_count += 1
            sma200 = _sma([o.value for o in w200])
            if current > sma200:
                above_200_count += 1

    if eligible_50_count == 0 or eligible_200_count == 0:
        raise BreadthUnavailableError(
            f"Breadth unavailable as of {as_of}: 0 of {total_members} members eligible "
            f"(sma50_eligible={eligible_50_count}, sma200_eligible={eligible_200_count})"
        )

    # [0,1] scale, matching the manifest's declared range for
    # pct_above_sma50/pct_above_sma200 (both {"minimum": 0, "maximum": 1}).
    # FOUND DURING SELF-REVIEW (Message[176]/[177]): the manifest declares
    # every score/percentile field [0,1], not 0-100 — an earlier version of
    # this function used a 0-100 scale (matching how a human would casually
    # describe "percent"), which is a real cross-slice inconsistency with
    # the manifest's own published contract, fixed here per the human's
    # explicit direction to rescale at the manifest-field boundary.
    pct_above_sma50 = above_50_count / eligible_50_count
    pct_above_sma200 = above_200_count / eligible_200_count
    # `breadth_eligible_count` is manifest-declared scalar (shape: "scalar"),
    # so one combined count is needed even though pct_above_sma50 and
    # pct_above_sma200 can have genuinely different eligible-member counts.
    # DESIGN CHOICE (not dictated by the design doc, flagged explicitly
    # rather than silently baked in): take the more conservative (smaller)
    # of the two, since this field is a consumer of `crisis_valid_domain_count`
    # per the manifest's own consumer list — understating eligibility is the
    # fail-closed-safe direction for a value that feeds crisis-domain
    # validity counting, never the reverse.
    eligible_count = min(eligible_50_count, eligible_200_count)

    return pct_above_sma50, pct_above_sma200, eligible_count, total_members


def compute_breadth(
    collection: RawSeriesCollection,
    as_of: str,
    sma50_window: int,
    sma200_window: int,
    blend: BreadthBlendConfig,
    source_tier: str = "tier_2_fixed_nine_production",
) -> BreadthResult:
    """Full Breadth computation for one as_of date. Raises
    BreadthUnavailableError if participation cannot be computed (fail-closed,
    never returns a neutral/default score in that case)."""
    pct_50, pct_200, eligible, total = compute_participation(collection, as_of, sma50_window, sma200_window)

    # pct_above_* are on [0,1] (matching the manifest's declared range);
    # a weighted sum of two [0,1] values with nonnegative weights summing to
    # one stays in [0,1], matching breadth_score's own declared range.
    score = blend.weight_sma50 * pct_50 + blend.weight_sma200 * pct_200

    return BreadthResult(
        as_of=as_of,
        source_tier=source_tier,
        eligible_count=eligible,
        total_members=total,
        pct_above_sma50=pct_50,
        pct_above_sma200=pct_200,
        breadth_score=score,
    )
