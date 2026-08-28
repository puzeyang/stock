# Market Regime v5.1 — Reference Implementation

This folder is the v5.1 reference engine, moved here from `research/regime/`
on 2026-08-27 (all v5.1 code/docs/schema/discussion; the older v7.2/v1.0
engines and pre-v5.1 design docs stay under `research/regime/`, which has
its own separate git history — `research/` is its own repo).

## Layout

| Path | Contents |
|---|---|
| `src/v5_1/` | The engine itself — modules 4.1–4.13 (contracts/primitives, raw features, Direction/TrendQuality, Breadth, Risk Appetite, Stability, Condition/Vetoes/Caps, the State Machine, Impulse, Confidence, Output Assembly, the Replay Interface, plus `engine.py`'s orchestrator scaffolding). |
| `tests/v5_1/` | The full test suite (450 tests as of the move). Run with `python3 -m pytest regime/tests/v5_1/ -v` from the repo root. |
| `docs/` | The design doc (`Market_Regime_Design_v5.1.md` + `_cn.md`), the approved implementation plan, and the frozen `Freshness_Threshold_Experiment_v1.0.md` spec. |
| `schema/` | The field manifest, field-ownership map, expected-session calendar, consumer graph, manifest schema, and the **frozen** freshness injection registry. |
| `tools/` | Standalone verifier/builder scripts — `verify_field_ownership.py`, `verify_freshness_registry.py`, `validate_output_contract.py`, `build_expected_session_calendar.py`, `update_source_snapshots.py`. |
| `discussion/` | `market-regime-discussion.md` (the append-only CLAUDE/CHATGPT/human discussion log) and `state.json` (turn-control state for that log). |

## Frozen artifacts — do not edit

Two files are **frozen** and must never change, at all, for any reason
(their exact bytes are load-bearing for the freshness threshold
experiment's own preregistration):

- `docs/Freshness_Threshold_Experiment_v1.0.md` — SHA-256
  `c5899dfc7359eab220e1aeba070474800f6bf19b49c10e9615597cf3adde9a0a`
- `schema/freshness_injection_registry.v1.0.json` — SHA-256
  `7b4e9697607bc62147b7074949a24d9ad3b1b51f73b91ea37d730d90947047fe`

Both hashes were re-verified byte-identical immediately before and after
this move.

## Known, deliberate inconsistency: the frozen registry's stale paths

`schema/freshness_injection_registry.v1.0.json`'s own `traceability` block
contains path strings like `"research/regime/docs/Market_Regime_Design_v5.1.md"`
and hashes like `manifest_sha256_at_registry_build` — these describe the
state of the world **at freeze time** (2026-08-25/26), before this move.
Since the registry's bytes are frozen and must never be edited, these
references are now stale and were left that way **on purpose** (human
decision, 2026-08-27): they are historical provenance, not a live pointer.

The direct consequence: running `tools/verify_freshness_registry.py` now
reports a `FAIL` on 11 `traceability.*` checks — every one of them is this
exact stale-path/stale-hash situation, not a real defect. The manifest
(`market_regime_fields.v5.1.json`), the field-ownership map, the expected-
session calendar, and the calendar builder/verifier scripts were all
themselves updated post-move (their own internal path references were
fixed to say `regime/...` instead of `research/regime/...`, since none of
*them* are frozen) — which necessarily changed their own content hashes,
which is exactly what the frozen registry's stale `..._sha256_at_registry_build`
fields now disagree with. This is expected and does not indicate any data,
logic, or provenance problem with the engine itself — every module's own
test suite (`pytest regime/tests/v5_1/`) passes cleanly from this new
location, and `tools/verify_field_ownership.py` (which does not depend on
the frozen registry at all) passes cleanly too.

If the freshness experiment's specification is ever revised/refrozen (per
the implementation plan's own §8 framing — a separate, subsequent,
human-scoped piece of work), that would be the natural point to also
re-register a fresh registry with corrected traceability, rather than
editing this one.

## Running things from the new location

```bash
# Full test suite
python3 -m pytest regime/tests/v5_1/ -v

# Field ownership conformance (does not touch the frozen registry)
python3 regime/tools/verify_field_ownership.py

# Freshness registry conformance (will report the known stale-traceability
# FAIL described above — everything else in it still passes)
python3 regime/tools/verify_freshness_registry.py
```

All run from the repo root (`stock/`).
