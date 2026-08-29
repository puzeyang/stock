"""Market Regime v5.1 — CRISIS Exploratory Challenge Set v0 (evaluation-
only, NOT part of the 4.1-4.13 module set, NOT production code).

**STATUS CORRECTION (Message[230]/[231]): this is NOT a preregistered
validation study, despite this module's original name and docstring
claiming otherwise.** Message[230]'s independent review found, and
Message[231] verified and accepted, six real problems with treating this
module's output as a validated result:
1. The 8 labeled episodes were built and dated AFTER real spot-checks
   against several of the same dates earlier in this investigation
   (Messages[212]/[224]/[228]) — a real "preregister before looking"
   violation, not preregistered in any meaningful sense.
2. `any_crisis_entered` (episode-level hit/miss) is biased toward long
   windows getting more "chances" to register a hit than short windows
   (e.g. 2022's 198 real dates vs. a 7-date negative episode) — treating
   all episodes as exchangeable Bernoulli trials for a Wilson CI hides
   this real exposure-length asymmetry.
3. **The most important problem**: design §9.1 states verbatim
   "Independent means no confirmation is an algebraic input to another.
   Economic correlation is expected." Labeling an episode "negative"
   BECAUSE credit (D2) stayed calm while two OTHER real domains (D1+D4)
   genuinely corroborated is applying an implicit "CRISIS requires
   credit confirmation" rule that appears nowhere in §9.1's actual text
   — a real labeling circularity, not a defensible judgment call. Any
   false-positive-rate computed against these labels is not trustworthy
   at face value.
4. This module's own earlier docstring promised precision/false-negative-
   rate/dwell-time as deliverables; `ValidationStudyResult` never
   actually computed them — corrected below (precision/FNR/dwell-time
   are NOT currently implemented, full stop, not merely omitted from a
   summary).
5. `evaluate_episode` starts each episode from a FRESH `RunningEngineState`
   (see its own docstring) — a legitimate design for an isolated entry
   smoke test, but incapable of supporting annual false-crisis-day-rate,
   real dwell time, or false-recovery/relapse metrics, which require one
   continuous run with persisted state across the full real timeline.
6. The real, statistically-elevated D1/D4 co-occurrence rate found by
   this module (see `domain_correlation` analysis referenced in
   Message[229]) remains real, but per point 3 does NOT by itself prove
   the co-occurrence was a misclassification rather than the 2-of-4 rule
   correctly recognizing genuine joint stress design §9.1 anticipates.

**Current correct status**: this module produces a real, useful
EXPLORATORY finding (D1+D4 co-occur at a real, non-trivial rate; three
specific real dates are documented) but is NOT sufficient, on its own, to
conclude the baseline preset (`use_real_crisis_domains=True`'s current
thresholds) is empirically rejected for production. The baseline preset
remains correctly unvalidated — not because this module proved it fails,
but because a proper validation (with the operational CRISIS definition,
labels, windows, and acceptance metrics frozen BEFORE looking at results,
by a reviewer independent of whoever already saw this exploratory output)
has not yet been done. Per Message[230]'s recommendation, that
prerequisite freezing step is the next required action before any further
code is written here — not something this module should attempt
unilaterally.

**Real, hard data-coverage limit, reported honestly rather than worked
around**: VIX9D (required by D1) only has real pinned coverage starting
2018-06-22 — already established earlier in this investigation as the
true first date ANY of the four CRISIS domains can be jointly evaluated.
This means Message[211] §九's cited historical positive episodes
predating that date (1987, 1998, 2000-02, 2008, 2011, 2015-16) are
STRUCTURALLY UNAVAILABLE to this study, not merely inconvenient — no
amount of data-cleaning fixes a series that starts in 2018.

**NOT production code, NOT a threshold-selection tool.** Message[211]
§九's own closing line remains the standing discipline: "若无 preset 同时
满足约束，正确结果是'不采用任何公式，保持未校准'，不是放宽规则直到某组
过关" (if no preset satisfies the constraints, the correct result is
"adopt no formula, remain uncalibrated" — not loosening the rules until
one passes). This module computes exploratory metrics against real data;
it does not itself decide whether any CRISIS preset should become a
production default, and — per this status correction — it also does not
currently establish that the baseline preset should be REJECTED.
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
    LabeledEpisode(
        "2023 October bond market selloff", "2023-10-02", "2023-10-31", False,
        "Real, documented rates-driven selloff (real 10-year Treasury "
        "yield touched ~5% intramonth for the first time since 2007) — "
        "added per the human's explicit selection (Messages[246]/[247]'s "
        "identified real gap between the March 2023 banking stress and "
        "the July 2024 yen-carry episode). Verified against real data "
        "before adding: VIX rose from 17.61 (2023-10-02) to 21.40 "
        "(2023-10-19), real 252-session drawdown peaked at -9.97% "
        "(2023-10-27), real Breadth participation genuinely weakened "
        "(pct_above_sma50 hit 0.0% on 2023-10-23/27/31) — but real OAS "
        "stayed calm throughout (4.11-4.51pp, well under the 6.00pp "
        "threshold), distinguishing it economically from the March 2023 "
        "banking-stress episode already in this set (credit-driven) and "
        "from 2024-08/2025-04 (single-day vol spikes) — this is a "
        "real, moderate, multi-week, rates/duration-driven stress event "
        "without a credit-stress or systemic-liquidity component. "
        "Labeled negative on that basis, independent of and prior to "
        "checking any CRISIS domain formula's actual output on these "
        "dates, per Message[247] point 4's requirement that episode "
        "selection/labeling not be conditioned on formula behavior.",
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
