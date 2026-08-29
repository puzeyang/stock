# continuous_domain_diagnostic_panel_v0

Pure descriptive diagnostic scripts for CRISIS's D1-D4 domains, per the
calibration-protocol discussion in `regime/discussion/market-regime-discussion.md`
Messages[247]-[253]. **NOT a validation study, NOT a threshold-selection
tool, and NOT preregistered** — these scripts describe the CURRENT
formulas' real behavior against the real full pinned timeline
(2018-06-22, VIX9D's real coverage floor, onward), they do not propose
or select any threshold. No script here modifies `crisis.py`/`engine.py`.

Every finding produced by these scripts, when referenced in the
discussion log, must carry the same non-preregistered/exploratory
caveat established for the 8-episode `crisis_validation.py` study in
Messages[230]/[231] — a broader real-timeline sample does not by
itself make a finding confirmatory.

## Scripts

- `panel_b_loo_matrix.py` — D4 Test A (universe jackknife): permanently
  removes one sector from the entire real history (affects SMA warm-up
  windows and the t-5 speed comparison too) and recomputes
  short_collapse/long_collapse/speed_collapse/extreme/active for every
  real date, producing a paired transition matrix (0→0/0→1/1→0/1→1)
  per sector per flag. Includes algebraic sanity-check assertions
  (Message[253]) that fail loudly if the real data ever contradicts
  the inequality-derived predictions.
- `panel_b_test_b.py` — D4 Test B (fixed-denominator member influence):
  keeps the real 9-member universe and denominator fixed; only
  counterfactually flips one member's real above/below-SMA state at a
  single date, isolating single-member influence from the
  9→8 denominator effect Test A conflates it with. **Speed-leg
  t-only/t-5-only/paired-path split is NOT YET implemented** (flagged
  as an open gap in Message[254], not silently completed).
- `diagnostic_panel_d2.py` — D2 absolute/relative branch contingency
  table across the full real timeline (Message[249]).
- `diagnostic_panel_d4.py` — original single-sided D4 short_collapse
  leave-one-out (Message[250]) — **superseded by
  `panel_b_loo_matrix.py`'s Test A**, which fixed the one-sided
  sampling and single-flag-scope gaps Message[251] identified. Kept
  for provenance/reproducibility, not as the current recommended
  script.

## Running

Each script is self-contained; run from the repo root:

```
python3 regime/panels/continuous_domain_diagnostic_panel_v0/panel_b_loo_matrix.py
python3 regime/panels/continuous_domain_diagnostic_panel_v0/panel_b_test_b.py
python3 regime/panels/continuous_domain_diagnostic_panel_v0/diagnostic_panel_d2.py
```

They read the same real pinned CSVs as `regime/tests/v5_1/` via
`load_manifest()`/`load_raw_series_bundle()` — no synthetic fixtures,
no network access.
