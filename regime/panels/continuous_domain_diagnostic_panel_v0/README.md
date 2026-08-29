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

- `_common.py` — shared D4-flag computation, transition-matrix helpers,
  and JSON output writer, imported by both Test A and Test B scripts
  below. Single source of truth so a script's docstring cannot drift
  ahead of its actual implementation the way Message[255] found
  `panel_b_loo_matrix.py`/`panel_b_test_b.py` had. Not imported by
  `crisis.py`/`engine.py` — has no production effect.
- `panel_b_loo_matrix.py` — D4 Test A (universe jackknife): permanently
  removes one sector from the entire real history (affects SMA warm-up
  windows and the t-5 speed comparison too) and recomputes the
  complete D4 evaluator for every real date under that 8-member
  universe. Persists per-sector transition matrices, k50/k200-
  stratified flip rates, date-level flip records, and active-spell
  counts to `outputs/`. Includes algebraic sanity-check assertions
  (Message[253]), re-verified from the persisted output on disk, not
  just in-memory state.
- `panel_b_test_b.py` — D4 Test B (fixed-denominator member influence):
  keeps the real 9-member universe and denominator fixed; runs FOUR
  non-overlapping scenario classes, never mixed into one score —
  `level_state_flip` (short/long/extreme only, speed explicitly
  EXCLUDED, not silently held at its real value while claiming to
  report `active`) and `speed_t_only`/`speed_t5_only`/
  `speed_paired_path` (each handles both endpoints of `drop_50_5d`
  explicitly and consistently, so `active` is trustworthy for these
  three). Fixes the internally-inconsistent mixing (real speed value
  used alongside a counterfactual current-day count) Message[255]/
  [256] found in the prior version — structurally impossible now,
  since `level_state_flip` cannot produce an `active` field at all.
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

## Outputs

`outputs/*.json` — one file per sector per scenario (Test A) or per
sector per scenario class (Test B), plus `*_summary.json` files. Every
file carries `schema_version: continuous_domain_diagnostic_panel_v0.outputs.v1`
and a `metadata` block (script path/hash, input manifest hash, D4
threshold constants, date floor) so a result can always be traced back
to the exact code and data that produced it. Regenerated on every
script run — not hand-edited, not committed as a claim of a completed
validation study (see the non-preregistered caveat above).
