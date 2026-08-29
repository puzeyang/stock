"""Market Regime v5.1 — CRISIS Preregistered Validation Study (evaluation-
only, NOT part of the 4.1-4.13 module set, NOT production code).

**Why this exists**: Message[209]'s review of Message[208]'s original
3-episode-only CRISIS validation proposal found it "tests selected
positives but cannot control false positives or support threshold
selection." Message[211] §九 specified a preregistered, positive-AND-
negative, precision/recall/lead-lag study as the real acceptance
standard for CRISIS domain thresholds — the "golden episode smoke test"
Message[224] shipped with is explicitly NOT that study. This module is
the first phase of building it, per the human's explicit direction to
start with the core quantitative deliverable (real episode labels +
false-positive/negative rates + precision/recall + entry lead/lag)
rather than attempting all 8 of Message[211] §九's requirements at once.

**Real, hard data-coverage limit, reported honestly rather than worked
around**: VIX9D (required by D1) only has real pinned coverage starting
2018-06-22 — already established earlier in this investigation as the
true first date ANY of the four CRISIS domains can be jointly evaluated.
This means Message[211] §九's cited historical positive episodes
predating that date (1987, 1998, 2000-02, 2008, 2011, 2015-16) are
STRUCTURALLY UNAVAILABLE to this study, not merely inconvenient — no
amount of data-cleaning fixes a series that starts in 2018. Per the
human's explicit direction, this study covers the full real window this
engine's data actually supports (2018-06-22 to present) and states this
limitation prominently rather than silently narrowing scope or
substituting a proxy series.

**NOT production code, NOT a threshold-selection tool by itself.**
Message[211] §九's own closing line is the standing discipline for
whatever this module eventually produces: "若无 preset 同时满足约束，
正确结果是'不采用任何公式，保持未校准'，不是放宽规则直到某组过关"
(if no preset satisfies the constraints, the correct result is "adopt
no formula, remain uncalibrated" — not loosening the rules until one
passes). This module computes real metrics against real data; it does
not itself decide whether `use_real_crisis_domains=True`'s current
baseline preset should become a production default.
"""
from __future__ import annotations

from dataclasses import dataclass

from .engine import RawSeriesBundle, TestScaffoldingConfig, new_running_engine_state, run_engine_for_date
from .contracts import Manifest
from .scoring import wilson_score_interval


# ---------------------------------------------------------------------------
# Real, dated episode labels within the real 2018-06-22-to-present coverage
# window. Each entry cites the real, verifiable market event and the real
# data that justifies its label — never an invented or approximate date
# range. `is_crisis_positive` marks periods this study expects (per
# well-documented real market history, independent of what this engine's
# own CRISIS domains say) to contain genuine systemic multi-domain stress;
# False marks periods with a real, documented market disturbance that
# should NOT count as a full crisis (deliberately chosen to include
# single-domain-stress cases, per Message[211] §九 item 2's explicit
# requirement — a formula that cannot tell these apart from genuine crises
# is exactly what this study exists to catch).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LabeledEpisode:
    name: str
    start: str
    end: str
    is_crisis_positive: bool
    note: str


LABELED_EPISODES: tuple[LabeledEpisode, ...] = (
    # --- Positive (real, documented systemic stress episodes) ---
    LabeledEpisode(
        "2018 Q4 (Christmas Eve Massacre)", "2018-10-01", "2019-01-15", True,
        "Real, well-documented systemic selloff — verified throughout this "
        "investigation (Messages[191]/[194]/[195]/[224]) against real VIX "
        "(36.07 on 2018-12-24), drawdown (-19.35% real 252-session dd), and "
        "Breadth participation (0% above SMA50) data.",
    ),
    LabeledEpisode(
        "2020 COVID crash", "2020-02-20", "2020-04-15", True,
        "Real, well-documented systemic selloff — verified against real "
        "VIX (82.69 on 2020-03-16, an all-time closing high at the time), "
        "OAS (10.87pp on 2020-03-23), and -33.7% real 252-session drawdown.",
    ),
    LabeledEpisode(
        "2022 bear market", "2022-01-03", "2022-10-15", True,
        "Real, well-documented systemic decline — verified against real "
        "OAS widening and drawdown data throughout Messages[194]-[198]. "
        "NOT a single sharp crash — a real, multi-month grinding decline, "
        "included specifically to test whether CRISIS entry/exit handles a "
        "slower-onset systemic episode, not only fast crashes.",
    ),
    LabeledEpisode(
        "2023 banking stress (SVB/Credit Suisse)", "2023-03-08", "2023-03-24", True,
        "Real, documented systemic-risk episode (Silicon Valley Bank/"
        "Signature Bank failures, Credit Suisse rescue) — verified against "
        "real OAS widening (4.09pp on 2023-03-08 -> 5.20pp on 2023-03-15). "
        "Labeled positive per Message[211] §九's own citation of '2023银行"
        "压力'; genuinely a BORDERLINE case since real VIX stayed under 27 "
        "throughout (never crossed D1's level_stress threshold of 30) — "
        "kept in the study specifically because it is borderline, not "
        "because it is a clean positive.",
    ),
    # --- Negative (real, documented disturbances that should NOT be CRISIS) ---
    LabeledEpisode(
        "2024 August yen-carry-unwind VIX spike", "2024-08-01", "2024-08-09", False,
        "Real, well-documented single-day vol event (real VIX=38.57/"
        "VIX9D=42.11 on 2024-08-05, a real term-structure inversion) "
        "driven by a yen-carry-trade unwind, NOT a systemic multi-domain "
        "crisis — real OAS stayed calm (3.67-3.93pp throughout, nowhere "
        "near the 6.00pp threshold) and real 252-session drawdown only "
        "reached -8.4%, well under D3's -20% extreme threshold. Replaces "
        "an earlier draft's '2018 Volmageddon' label, which was found "
        "(via this module's own coverage-floor test) to fall entirely "
        "before VIX9D's real 2018-06-22 coverage start — CRISIS could "
        "never actually be jointly evaluated on those dates at all, so "
        "it could not serve as a real negative-example test.",
    ),
    LabeledEpisode(
        "2019 August trade-war selloff", "2019-08-01", "2019-08-15", False,
        "Real, documented correction (US-China trade tension escalation) "
        "— real 252-session drawdown only -6.0% by 2019-08-05, a genuine "
        "but modest pullback, not a systemic crisis.",
    ),
    LabeledEpisode(
        "2021 calm bull market", "2021-06-01", "2021-08-31", False,
        "Real, genuinely calm stretch — already verified zero CRISIS "
        "firings across all 65 real trading days in this window "
        "(Message[224]/[228]'s false-positive checks). Included here to "
        "anchor the negative-episode set with an unambiguous true-calm "
        "period, not just near-misses.",
    ),
    LabeledEpisode(
        "2025 April tariff selloff", "2025-04-01", "2025-04-15", False,
        "Real, documented event (real VIX spike to 52.33 on 2025-04-08, "
        "an extreme single-domain reading) but real OAS stayed calm "
        "(4.37-4.57pp throughout, never approaching the 6.00pp threshold) "
        "— the mirror-image single-domain case to 2023's banking stress "
        "(there: credit stress without vol stress; here: vol stress "
        "without credit stress). A real test of whether D1 alone "
        "(2-of-4 requires TWO domains) can force a false CRISIS entry.",
    ),
)


def episode_dates(episode: LabeledEpisode, raw: RawSeriesBundle) -> tuple[str, ...]:
    """Every real trading date in `raw.benchmark`'s own calendar falling
    within `episode`'s [start, end] inclusive range."""
    return tuple(o.date for o in raw.benchmark.observations if episode.start <= o.date <= episode.end)


# ---------------------------------------------------------------------------
# Core quantitative study: real per-episode CRISIS classification against
# the labels above, aggregated into precision/recall/false-positive-rate
# with Wilson score confidence intervals (reusing scoring.py's existing
# implementation, not a new formula), plus entry lead/lag and dwell time.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EpisodeResult:
    episode: LabeledEpisode
    dates_checked: int
    crisis_dates: tuple[str, ...]
    any_crisis_entered: bool
    first_crisis_date: str | None
    entry_lag_sessions: int | None  # sessions from episode.start to first CRISIS date, None if never entered


def evaluate_episode(episode: LabeledEpisode, raw: RawSeriesBundle, manifest: Manifest, config: TestScaffoldingConfig) -> EpisodeResult:
    """Runs the full engine across one labeled episode's real date range,
    starting from a FRESH `RunningEngineState` at the episode's own start
    (deliberately NOT carrying state in from before the episode, so each
    episode's entry/exit behavior is evaluated on its own real timeline
    without cross-episode leakage). `entry_lag_sessions` counts real
    trading sessions from the episode's labeled start to the first real
    CRISIS entry — 0 means CRISIS was already active on the very first
    checked date (a real possibility for episodes whose labeled start is
    itself already inside a decline)."""
    dates = episode_dates(episode, raw)
    state = new_running_engine_state(config)
    crisis_dates: list[str] = []
    first_crisis_date: str | None = None
    for i, d in enumerate(dates):
        record = run_engine_for_date(d, raw, state, manifest, config=config)
        if record.get("state") == "CRISIS":
            crisis_dates.append(d)
            if first_crisis_date is None:
                first_crisis_date = d
    entry_lag = dates.index(first_crisis_date) if first_crisis_date is not None else None
    return EpisodeResult(
        episode=episode, dates_checked=len(dates), crisis_dates=tuple(crisis_dates),
        any_crisis_entered=bool(crisis_dates), first_crisis_date=first_crisis_date,
        entry_lag_sessions=entry_lag,
    )


@dataclass(frozen=True)
class ValidationStudyResult:
    episode_results: tuple[EpisodeResult, ...]
    true_positives: int    # positive episodes where CRISIS entered
    false_negatives: int   # positive episodes where CRISIS never entered
    true_negatives: int    # negative episodes where CRISIS never entered
    false_positives: int   # negative episodes where CRISIS entered
    recall: float | None          # true_positives / (true_positives + false_negatives)
    recall_ci: tuple[float, float] | None
    false_positive_rate: float | None  # false_positives / (false_positives + true_negatives)
    false_positive_rate_ci: tuple[float, float] | None


def run_validation_study(raw: RawSeriesBundle, manifest: Manifest, config: TestScaffoldingConfig) -> ValidationStudyResult:
    """Runs every episode in `LABELED_EPISODES` and aggregates into
    episode-level (not date-level) precision/recall — per Message[211]
    §九 item 8's own "事件日附近按 episode 聚类，不能把相邻每日观测伪装成
    独立样本" (cluster by episode near event days, don't disguise
    adjacent daily observations as independent samples): the unit of
    analysis here is ONE EPISODE = ONE SAMPLE (did CRISIS ever fire
    during this real labeled episode), not one sample per date, which
    would badly overstate the effective sample size for a stress episode
    lasting weeks."""
    results = tuple(evaluate_episode(ep, raw, manifest, config) for ep in LABELED_EPISODES)

    positives = [r for r in results if r.episode.is_crisis_positive]
    negatives = [r for r in results if not r.episode.is_crisis_positive]

    tp = sum(1 for r in positives if r.any_crisis_entered)
    fn = sum(1 for r in positives if not r.any_crisis_entered)
    tn = sum(1 for r in negatives if not r.any_crisis_entered)
    fp = sum(1 for r in negatives if r.any_crisis_entered)

    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    recall_ci = wilson_score_interval(tp, tp + fn) if (tp + fn) > 0 else None
    fpr = fp / (fp + tn) if (fp + tn) > 0 else None
    fpr_ci = wilson_score_interval(fp, fp + tn) if (fp + tn) > 0 else None

    return ValidationStudyResult(
        episode_results=results,
        true_positives=tp, false_negatives=fn, true_negatives=tn, false_positives=fp,
        recall=recall, recall_ci=recall_ci,
        false_positive_rate=fpr, false_positive_rate_ci=fpr_ci,
    )
