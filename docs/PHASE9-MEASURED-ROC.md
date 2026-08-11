# Phase 9 — Measured ROC Integration

Status: **Phase 9 result — real thresholds derived into the frozen SBA frame.**
CLAUDE.md was NOT modified by this pass (hash `3acda0e853af3f446ac7fb33567fed10`
before, unchanged after). Code: `roc_estimability/threshold_derivation.py`,
`experiments/phase9_measured_roc.py`, `tests_roc_estimability/test_threshold_derivation.py`,
`harnesses/mutation_check_threshold_derivation.py`.
Artifacts: `artifacts/phase9_measured_roc_report.json`,
`provenance/phase9_measured_roc_manifest.json`, `config/eis.v1-measured.json`.

---

## 0. What this is, and isn't

This derives real per-(claim, budget) thresholds from real Phase 8 evidence-producer
distributions on real BCIC IV 2a data, per CLAUDE.md §20's already-frozen SBA
methodology (event model, apportionment, Tail-Floor Rule). It does **not** modify
that methodology, the event model, the budgets, the apportionment formula, or any
wire/config format. `config/eis.v0.json` and `config/eis.v1.json` are both
byte-identical before and after (confirmed by hash, §5).

---

## 1. Cohort design (unchanged from the frozen per-claim table)

| Claim | Cohort | min subjects separating |
|---|---|---|
| Model, Device, FSI | held-out {4–9} | 4 of 6 |
| Signal, Calibration | full {1–9} | 6 of 9 |
| ActuationFidelity | not assessed (no offline measurement exists) | — |

---

## 2. This driver's own concretizations (flagged explicitly, not previously pre-registered)

CLAUDE.md §20 fixed the *methodology* for α/β but explicitly left concrete numeric
choices to "Phase 9's output." Three concretizations were made here:

1. **α for Model/Device/FSI** (no continuous stream exists to measure an event
   model on): Phase 8.5's flat per-window formula
   (`session_to_window_budget` → `flat_split_alpha` over the 5 strict claims),
   applied **unmodified** to every claim including Device (the one lenient claim) —
   CLAUDE.md §20 does not differentiate the α *derivation* by strict/lenient status,
   only policy's downstream severity handling does.
2. **β** (per-dimension, consequence-exposure-derived methodology, no formula fixed):
   `β_dim = B`, the same swept budget value, applied identically per claim — the
   simplest reading of §20's Note that a T5-severed β "receives the identical
   illustrative-sweep treatment as α."
3. **Deployed operating point**: `config/eis.v1-measured.json`'s single global
   `alpha_ppb`/`beta_ppb` (the wire-adjacent config format holds one operating point,
   not three) is set at the **nominal 1%/8h budget**. All three swept budgets'
   θ1/θ2/band_cap/resolution_status are reported in full below and in the JSON
   report — the swept sweep is a reported feasible region, the same status as
   Env/Ceil's reference table (CLAUDE.md §6), not simultaneously representable in
   this config schema.

---

## 3. Real per-subject test accuracy (context only — never a success criterion, CLAUDE.md §17a)

| Subject | Test accuracy |
|---|---|
| 1 | 0.596 | 2 | 0.592 | 3 | 0.553 | 4 | 0.362 | 5 | 0.496 |
| 6 | 0.369 | 7 | 0.521 | 8 | 0.457 | 9 | 0.457 |

(chance = 0.25 for 4-class motor imagery; reported as pipeline substrate context,
not a Phase 9 result — CLAUDE.md §17a's scope guard.)

---

## 4. Event model — full 9-subject pool (Signal/Calibration only)

`docs/EVENT-MODEL-INVESTIGATION.md` measured subjects 1–3 only. Phase 9's
Signal/Calibration cohort is the full 9-subject pool, so all 9 were measured fresh
here (real continuous-stream sliding-window pass, `event_model.continuous_stream`).
Subjects 1–3's N_onsets reproduce the earlier 3-subject investigation's values
closely (subject 1 Signal: 3759.4 here vs 3759 there) — a reproducibility check,
not assumed.

| Subject | Signal N_onsets/session | Calibration N_onsets/session |
|---|---|---|
| 1 | 3759.4 | 7426.5 |
| 2 | 3788.7 | 5433.5 |
| 3 | 4105.4 | 7683.9 |
| 4 | 2304.3 | 7705.0 |
| 5 | 16883.8 | 5595.8 |
| 6 | 5174.8 | 4372.1 |
| 7 | 4145.2 | 8184.6 |
| 8 | 3452.4 | 10203.5 |
| 9 | 4245.9 | 13405.7 |
| **mean (used for α)** | **5317.8** | **7779.0** |

Subject 5 (Signal) and subject 9 (Calibration) are real outliers (much longer
episode+gap cycles than the rest); reported as measured, not smoothed over. The
mean N_onsets across all 9 feeds `event_model.availability.episode_alpha(B, N_onsets)`
for these two claims' α at each swept budget.

---

## 5. Per-(claim, budget) derivation — full results

θ1/θ2 are in each claim's own real `raw_measurement` scale (not ppb — that scale is
internal to the α/β comparison only). `resolution_status` folds θ1's and θ2's
independently-evaluated Tail-Floor Rule verdicts into the single value
`config/eis.v1.json`'s existing schema field can hold: `tail_floor` if **either**
side triggers, `stable` only if both do not (the conservative direction).

| Claim | Budget | α | β | θ1 | θ2 | band_cap | resolution_status |
|---|---|---|---|---|---|---|---|
| Signal | 0.1% | 1.88e-7 | 1e-3 | −100 | −99 | HIGH | **tail_floor** |
| Signal | 1% | 1.88e-6 | 1e-2 | −100 | −99 | HIGH | **tail_floor** |
| Signal | 5% | 9.40e-6 | 5e-2 | −100 | −99 | HIGH | **tail_floor** |
| Calibration | 0.1% | 1.29e-7 | 1e-3 | −100 | 11 | HIGH | **tail_floor** |
| Calibration | 1% | 1.29e-6 | 1e-2 | −100 | 5 | HIGH | **tail_floor** |
| Calibration | 5% | 6.43e-6 | 5e-2 | −100 | 0 | HIGH | **tail_floor** |
| Model | 0.1% | 6.95e-10 | 1e-3 | 100 | 100 | HIGH | stable |
| Model | 1% | 6.98e-9 | 1e-2 | 100 | 100 | HIGH | stable |
| Model | 5% | 3.56e-8 | 5e-2 | 100 | 100 | HIGH | stable |
| Device | 0.1% | 6.95e-10 | 1e-3 | 100 | 100 | HIGH | stable |
| Device | 1% | 6.98e-9 | 1e-2 | 100 | 100 | HIGH | stable |
| Device | 5% | 3.56e-8 | 5e-2 | 100 | 100 | HIGH | stable |
| FSI | 0.1% | 6.95e-10 | 1e-3 | 100 | 100 | HIGH | stable |
| FSI | 1% | 6.98e-9 | 1e-2 | 100 | 100 | HIGH | stable |
| FSI | 5% | 3.56e-8 | 5e-2 | 100 | 100 | HIGH | stable |

**Exactly matches the pre-registered "measured resolution note" (CLAUDE.md §20):**
Signal and Calibration fall under the Tail-Floor Rule at **all three** swept
budgets, not just the tightest — measured here, not assumed, on the real full
9-subject pool. Model/Device/FSI are stable at all three, confirming the
ROC-estimability diagnostic's held-out-cohort-sufficient recommendation.

Every θ1/θ2 above marked `tail_floor` is a **conservative floor** ("no tighter
than X"), not a point estimate — the most extreme empirically resolvable operating
point the real data reaches, per the Tail-Floor Rule's own construction (never a
parametric extrapolation).

**A new, honest finding this pass surfaced (not previously checked):** the flat
per-window α used for Model/Device/FSI is itself **below the ppb representability
floor** at the tightest swept budget (0.1%: α≈6.95e-10, margin 0.69× — under 1×).
It only becomes a nonzero stored `alpha_ppb` value (1) via `round()`'s upward
rounding, not because it was genuinely representable at that resolution.
`docs/EVENT-MODEL-INVESTIGATION.md`/`eis_v1_precision_validation.py` only checked
ppb representability for the 18 *episode-based* (Signal/Calibration) combinations —
this per-window flat-split value was never checked against ppb before. Recorded
per-budget in `artifacts/phase9_measured_roc_report.json`'s
`claims.*.budgets.*.alpha_representability`.

**Disposition of the sub-ppb case, stated explicitly (not left implicit).** The
driver did not resolve this by hitting the true 6.95e-10 rate on a continuous
curve — it couldn't, no representation does. It resolved it because Model/Device/
FSI's ROCs are **degenerate**: honest and attack scores fall into two disjoint
clusters (e.g. Device: honest={100}, attack={-100}) with `FPR(t) = 0` at *every*
candidate threshold up to the tightest observed point, and no candidate at all in
between the clusters. `derive_thresholds()`'s `theta1 = max{t : FPR(t) <= alpha}`
therefore lands on the same tightest-observed-threshold (`theta1 = 100`) for *any*
`alpha > 0` — checked directly: substituting `alpha_ppb` values from 1 up to
500,000,000 (i.e. alpha=0.5) into the real, unmodified `derive_thresholds()` against
Device's actual measured ROC returns `theta1 = theta2 = 100` in every case, no
change. The operating point is determined by the **class gap**, not by locating a
rate along a curve — the sub-ppb nominal target simply never binds, because there
is no data in the gap it could bind against. This is also why the Tail-Floor Rule's
own criteria (class separation, bootstrap width, LOSO swing — §9) independently
returned `stable`: those criteria test the stability of the *data*, not whether
`alpha` was resolved to its exact nominal value, and a two-cluster degenerate
separation is maximally stable under all three.

Contrast Signal/Calibration: their ROCs are continuous (real Welch-PSD/drift-
distance values spread across ~100+ distinct points, §5's `n_roc_points` column
matches), so a sub-resolution `alpha` (or `beta`) genuinely *does* select a specific,
data-dependent point along that curve rather than landing in an unresolvable gap —
and it is exactly there that the Tail-Floor Rule fires (§5), because that specific
point is exactly what the class-support/bootstrap/LOSO criteria found unstable on
the available sample sizes. The two claims' outcomes differ for a real, structural
reason (degenerate vs. continuous ROC shape), not by chance.

---

## 6. Real measurements that became interpretable (were LOW-by-placeholder in Phase 8)

`experiments/phase8_evidence_producers.py`'s own report noted that Signal and
Calibration's real raw measurements were LOW under the still-placeholder
`eis.v0.json` ROC/θ config (calibrated against synthetic values, never fit to real
producer output) — masking the FSI-strict-vs-Device-lenient CTPR distinction that
driver existed to demonstrate. Under the measured config here, that real Signal/
Calibration data is now interpreted against real, data-derived θ1/θ2 rather than a
synthetic placeholder scale — the spine sanity check (§7) confirms honest values
(now well inside the real θ2 boundary) correctly band HIGH, and attack-like values
correctly floor LOW, using the actual measured scale rather than an arbitrary one.

---

## 7. Config transition

`calibration_status` was attempted at `"measured"`. `trust_kernel.bands.validate_eis_config()`'s
existing fail-closed check **correctly refused**:

> `calibration_status is 'measured' but claim 'actuationfidelity.provisional_v0' is still a placeholder derivation`

This is the correct, working gate (CLAUDE.md §13/§20), not a defect — ActuationFidelity
has no offline per-subject measurement path in this architecture (no live enforcement
loop to compare commanded-vs-observed against, offline). `config/eis.v1-measured.json`
was therefore written with `calibration_status: "provisional"`, five of six claims
real (`placeholder: false`), ActuationFidelity untouched (`placeholder: true`,
`resolution_status` all `pending`).

- `config/eis.v0.json` hash: unchanged, matches known-good `087f66e28eb3...` ✓
- `config/eis.v1.json` (placeholder) hash: unchanged, matches known-good `cfeb34557ee...` ✓
- `config/eis.v1-measured.json` `roc_config_hash()`: `beb166a43c77c59edccc373941b6c2272c37c8b71027eb59a358d0ae034bf4d3` (new)

---

## 8. Spine sanity check (P1 gate: no architectural finding)

Real signed statements, built at each dimension's own measured θ1/θ2 as reference
points, run through the real, unmodified `trust_kernel.bands`/`ctpr`/`policy` code
path (`tests.window_fixtures.compute_verdict`, config overridden to the new file —
no kernel code touched). Result:

| Dimension | Case | Verdict |
|---|---|---|
| Signal, Model, Calibration, FSI, ActuationFidelity | honest | Normal |
| Signal, Model, Calibration, FSI, ActuationFidelity | attack | **Safe** |
| Device | honest | Normal |
| Device | attack | **Constrained** (not Safe) |

The strict/lenient distinction (CLAUDE.md §4) reproduces correctly, driven entirely
by the measured config's real thresholds. `trust_kernel/{canon,schema,bands,ctpr,policy,sign}.py`
were not written to by this driver at any point (confirmed by listing their hashes
in the report; no `Edit`/`Write` call touched them in this pass). **No architectural
finding** — the measured config changes only which numeric thresholds are applied,
nothing about kernel mechanics.

---

## 9. Mutation kill rates

- `threshold_derivation` (new): **14/14 (100%)**
- pure core (`harnesses/mutation_check.py`): **61/61 (100%)**, unaffected
- `eis_v1` (`harnesses/mutation_check_eis_v1.py`): **11/11 (100%)**, unaffected

---

## 10. Known issue found and fixed: per-subject AUC reporting

`per_subject_auc` (a reported distribution only — CLAUDE.md §14: "NO success
criterion, NO subject exclusion") had an integration-boundary bug: the ROC curve
used for AUC never included a candidate threshold above the maximum observed score,
so the final segment out to FPR=1.0 was invisible to the trapezoidal sum. For
claims whose honest distribution is a single repeated ceiling value (Device/Model/
FSI), this silently capped every reported AUC toward 0.0 even under **perfect**
separation (independently confirmed by θ1=θ2=100, band_cap=HIGH, and the spine
sanity check's clean classification). Signal showed the same artifact for 7 of 9
subjects (repeated value `0.996453901` = `1 − 1/282`, the ceiling-artifact
signature); subjects 1 and 5 showed genuine, non-ceiling separation. Calibration's
9 values showed no repeated-ceiling signature (a real, spread continuous
distribution), marginally understated by the same missing segment.

**Scope of impact — reporting only.** θ1/θ2/band_cap/resolution_status,
`config/eis.v1-measured.json`, and the spine sanity check are all computed via a
separate code path (`derive_thresholds()` directly on the same `roc_points`, whose
formula never needed an upper sentinel) and are unaffected.

**Structural argument, not just corroboration.** θ1=θ2 and the spine check show the
*outputs* are correct; the claim that the AUC bug *could not have caused it* needs
the call graph, checked directly rather than assumed:

- `_per_subject_auc()` is called exactly once in `experiments/phase9_measured_roc.py`
  (`main()`, Pass 4), and its return value is stored only under
  `claim_results[claim]["per_subject_auc"]`.
- `build_measured_config(claim_results)` — the function that writes
  `config/eis.v1-measured.json` and computes its `roc_config_hash` — reads exactly
  two keys off each claim's result: `r["budgets"]` (which holds `theta1`/`theta2`/
  `band_cap`/`resolution_status`, produced by `derive_claim_operating_point()`) and
  `r["roc_points"]`. It never reads `r["per_subject_auc"]`. Grepped directly, not
  inferred: `"per_subject_auc"` appears in exactly two places in the whole file —
  its computation (line ~334) and its storage into the report dict (line ~341) —
  and nowhere in `build_measured_config()`, `spine_sanity_check()`, or anywhere in
  `roc_estimability/threshold_derivation.py`.
- `roc_estimability/threshold_derivation.py` — the module containing
  `derive_claim_operating_point()`, `build_roc_points()`, `evaluate_tail_floor_rule()`,
  and every function that touches θ1/θ2/resolution_status — has **zero** references
  to AUC anywhere in it (checked by grep). `_per_subject_auc()` lives only in the
  driver, calls the same shared, pure `td.build_roc_points()` function independently
  (no shared mutable state — `build_roc_points()` takes plain lists and returns a
  new list each call), and its own local trapezoidal sum has no return path back
  into anything `derive_claim_operating_point()` uses.
- `spine_sanity_check()` reads only the assembled config file off disk
  (`load_eis_config`), never `claim_results` at all.

So independence holds structurally, not only observationally: there is no code path
from `_per_subject_auc()`'s output to any threshold, config, or resolution_status
value — the θ1=θ2/spine-check corroboration and this call-graph argument agree, and
the isolation claim rests on both, not the corroboration alone.

Fixed in `experiments/phase9_measured_roc.py`'s `_per_subject_auc()` (appends the
standard ROC-closing corner before integrating) after this run completed. Per
instruction, the experiment was **not rerun**; the true values are documented
directly in `artifacts/phase9_measured_roc_report.json`'s
`claims.Signal.per_subject_auc_known_issue` (Device/Model/FSI/the 7 Signal
subjects: true AUC = 1.0; Signal subjects 1/5 and all Calibration subjects: real,
marginally understated values, already reported).

---

## 11. Feasibility region (α, β across the three swept budgets)

Per-session halt rate derived from the per-window α, via the frozen event model
(episode-counted for Signal/Calibration, per-window-flat-split for Model/Device/FSI/
Device), reported in full in §5's table and `artifacts/phase9_measured_roc_report.json`.
No point value is asserted as a deployment recommendation — per CLAUDE.md §28's
scope guard, this project has no target clinical stakeholder to source a real budget
from; the three swept budgets remain a reported feasible region.

---

## 12. Reproducibility

Full manifest: `provenance/phase9_measured_roc_manifest.json` (params, seeds, config
hashes, dataset pins via the pipeline's existing hash-verified loader, timestamp).
`post_hoc_report_annotation` in that manifest records the report's before/after
hash for the §10 correction, applied after the run completed without rerunning
the pipeline.
