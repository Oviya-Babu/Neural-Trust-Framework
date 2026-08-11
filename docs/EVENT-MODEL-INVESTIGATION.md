# Event-Counting Investigation — Prerequisite to Phase 9

Status: **investigation report for PI review — CLAUDE.md not modified by this pass.**
Code: `event_model/`, `tests_event_model/`, `harnesses/mutation_check_event_model.py`,
`experiments/event_model_investigation.py`.
Artifacts: `artifacts/event_model_investigation_report.json`,
`provenance/event_model_investigation_manifest.json`.

No real ROC/attack-derived thresholds were computed anywhere in this
investigation (only honest operation was measured); the wire/statement
schema and CLAUDE.md are unmodified; Phase 9 was not started.

---

## 0. The question

Phase 8.5's SBA formula (`docs/PHASE8.5-SBA-VALIDATION.md`) treats each of
the `fT = 288,000` windows in an 8h session as an **independent** Bernoulli
trial. Two things follow if that's wrong: (a) the per-window α derived
from a session budget is not the right quantity to reason about, and
(b) an **episode**-counted budget (apportioned over the number of
*interruptions*, not windows) might be both more architecturally correct
and — because far fewer episodes than windows occur per session —
numerically easier to represent at the config's current basis-point
granularity. This investigation measures whether that's actually true,
against the real pipeline, before anything is built on top of it.

---

## 1. Event model — empirical measurement

### 1.1 Method

Real, continuous (not epoched) session-E EEG for subjects 1–3
(BCIC IV 2a, hash-verified via `bci_pipeline.loader`), covering the full
2321.6s / 23,207-window session per subject at the real 100ms hop
(CLAUDE.md §7), with a 1.0s analysis window per hop (see
`event_model/continuous_stream.py`'s docstring for why a longer analysis
window is needed even though each measurement corresponds to one 100ms
step). Per hop, computed **directly via the real, unmodified**
`sensors.signal_sensor.measure_signal_quality` and
`sensors.calibration_sensor.measure_calibration_drift` — not
reimplementations. Model, Device, FSI, ActuationFidelity were **not**
included: under honest, single-session, no-live-enforcement-loop
operation, all four are discrete pass/fail integrity checks (§9
signature, DTLS handshake, TPM quote, actuator feedback) with no
continuously-varying real-valued measurement defined at streaming
100ms cadence in the current architecture — stated as an explicit scope
limitation, not a claim that they are perfectly reliable.

"Restricted" (LOW-band) is defined, per claim, as raw_measurement at or
below the claim's own empirical *P*-th percentile of the observed
honest-operation distribution — an **operating-point choice for this
investigation only**, not an ROC/attack-derived threshold (no attack data
appears anywhere in this analysis). Two percentiles were used: **P=5%**
(primary — matches the pre-committed Step-2 debounce percentile, giving a
single coherent number throughout) and **P=1%** (secondary, matches
SBA's nominal budget) as a robustness check.

### 1.2 Results — all three subjects, both claims, both percentiles

| Subject | Claim | P | lag-1 autocorr | run-length ratio (measured/independent) | Falsified? |
|---|---|---|---|---|---|
| 1 | Signal | 5% | 0.725 | 3.65× | **No** |
| 1 | Calibration | 5% | 0.794 | 5.60× | **No** |
| 2 | Signal | 5% | 0.710 | 3.45× | **No** |
| 2 | Calibration | 5% | 0.817 | 29.8× | **No** |
| 3 | Signal | 5% | 0.709 | 3.46× | **No** |
| 3 | Calibration | 5% | 0.779 | 5.15× | **No** |
| 1 | Signal | 1% | 0.719 | 3.56× | **No** |
| 1 | Calibration | 1% | 0.794 | 5.84× | **No** |
| 2 | Signal | 1% | 0.667 | 3.01× | **No** |
| 2 | Calibration | 1% | 0.817 | 31.1× | **No** |
| 3 | Signal | 1% | 0.745 | 3.93× | **No** |
| 3 | Calibration | 1% | 0.779 | 5.37× | **No** |

**Falsification criterion (pre-defined, mechanical, `experiments/event_model_investigation.py`'s
`falsification_verdict`):** falsified iff `|lag-1 autocorrelation| < 0.05`
**AND** `0.8 ≤ run-length ratio ≤ 1.5`. Neither condition held in any of
the 12 (subject × claim × percentile) cells measured — lag-1
autocorrelation is uniformly strong (0.67–0.82, an order of magnitude
above the 0.05 falsification bound), and measured restricted-run lengths
are 3–31× longer than an independent-draw process would produce.

### 1.3 Which argument survives

- **Architectural case** (interruptions, not windows, are the correct
  unit of an availability budget): stands on its own terms regardless of
  this measurement — it is a definitional claim about what "availability"
  means operationally, not an empirical one.
- **Practical case** (episode-counting materially changes α): **survives**
  — not a marginal result. Consistent, strong clustering across every
  subject and both operating points tested. This is a directional
  finding; §4 shows it does not, on its own, resolve §3.3's
  representability question.

### 1.4 A caveat on the measurement itself

The 1.0s analysis window with a 0.1s hop means **consecutive windows
share ~90% of their underlying samples by construction** — this
mechanically induces some of the measured lag-1 correlation, independent
of any genuine physiological persistence. Disclosed and checked, not
absorbed into the headline number: at lag-50 (5.0s apart — beyond the
1.0s analysis window entirely, so window-overlap contributes exactly
zero), the two claims diverge sharply and exactly as physically
expected:

| Subject | Claim | lag-1 | lag-2 | lag-5 | lag-10 | lag-50 (no window overlap) |
|---|---|---|---|---|---|---|
| 1 | Signal | 0.725 | 0.487 | 0.147 | 0.065 | −0.008 |
| 1 | Calibration | 0.794 | 0.669 | 0.402 | 0.124 | 0.023 |
| 2 | Signal | 0.710 | 0.464 | 0.094 | 0.033 | −0.003 |
| 2 | Calibration | 0.817 | 0.720 | 0.543 | 0.380 | **0.338** |
| 3 | Signal | 0.709 | 0.469 | 0.139 | 0.046 | 0.016 |
| 3 | Calibration | 0.779 | 0.643 | 0.388 | 0.139 | 0.033 |

**Signal's autocorrelation decays to ~0 by lag-50 in all three
subjects** — its lag-1 strength is consistent with being substantially a
window-overlap artifact plus short (few-hundred-ms) artifact bursts, not
long-range persistence. **Calibration's does not** — it remains clearly
positive at lag-50 in every subject (0.023–0.338), well past any window-
overlap explanation, confirming genuine slow drift, not a measurement
artifact. This is exactly the fast/slow distinction the task anticipated
for the *decay structure* — it is only the §4 *representability ordering*
that came out counter to expectation, and the two are reported
separately rather than conflated.

---

## 2. Step 2 — pre-committed debounce rule

Rule fixed in advance (task specification, `event_model/temporal_stats.py`'s
`percentile_debounce_interval`): D = smallest number of consecutive
Normal windows at which fewer than 5% of measured inter-restriction gaps
are shorter than D (percentile-boundary reading; the fully literal
reading is vacuous at D=1 — flagged for PI confirmation, same pattern as
CTPR's `g=identity`, CLAUDE.md §18).

| Subject | Claim | D | n episodes (merged) | mean episode length (windows) | mean gap (windows) |
|---|---|---|---|---|---|
| 1 | Signal | 5 | 303 | 4.360 | 72.248 |
| 1 | Calibration | 2 | 597 | 7.018 | 31.762 |
| 2 | Signal | 6 | 305 | 4.193 | 71.822 |
| 2 | Calibration | 2 | 438 | 44.174 | 8.831 |
| 3 | Signal | 5 | 331 | 4.085 | 66.067 |
| 3 | Calibration | 2 | 620 | 6.303 | 31.178 |

D was never 1–2 across the board (Signal: 5–6; Calibration: 2) —
consistent with §1's finding, **not** the "effectively no debounce"
outcome the task specified as the independent-draw signature. This is
itself corroborating evidence, not a separate test.

---

## 3. Step 3 — both availability equations, side by side

**Window-independence assumption, stated explicitly and tested directly
(§1):** it did **not** hold. `alpha = 1-(1-B)^(1/fT)` is derived exactly
as specified below regardless — it is reported as the honest per-window
number, not as a claim that per-window independence is true.

```
Per-window:  α = 1 − (1−B)^(1/fT),   fT = 288,000
Episode:     α_onset = B / N_onsets,  N_onsets = fT / (mean episode length + mean gap)
```

| Session budget B | α (per-window) | α (bp) | Representable? |
|---|---|---|---|
| 0.1% | 3.474 × 10⁻⁹ | 0.000035 | No |
| 1% | 3.490 × 10⁻⁸ | 0.000349 | No |
| 5% | 1.781 × 10⁻⁷ | 0.001781 | No |

(Per-window α is claim-independent — the formula only uses B and fT — so
one row per budget suffices; this reproduces Phase 8.5's finding exactly,
now cross-checked against a second, independent derivation path.)

Episode α, per subject/claim (representative: subject 1; subjects 2–3 in
the artifact JSON follow the same pattern within the range shown in §4):

| Claim | B | N_onsets/session | α (episode) | α (bp) | Representable? |
|---|---|---|---|---|---|
| Signal | 0.1% | 3759 | 2.660 × 10⁻⁷ | 0.00266 | No |
| Signal | 1% | 3759 | 2.660 × 10⁻⁶ | 0.02660 | No |
| Signal | 5% | 3759 | 1.330 × 10⁻⁵ | 0.13300 | No |
| Calibration | 0.1% | 7427 | 1.347 × 10⁻⁷ | 0.00135 | No |
| Calibration | 1% | 7427 | 1.347 × 10⁻⁶ | 0.01347 | No |
| Calibration | 5% | 7427 | 6.733 × 10⁻⁶ | 0.06733 | No |

Episode-counting improves α by **1–2 orders of magnitude** over
per-window (e.g. Signal @ B=1%: 3.49×10⁻⁸ → 2.66×10⁻⁶, a ~76× improvement,
matching the measured mean-episode+gap cycle length almost exactly — this
is the formula behaving correctly, not a surprise). It does **not** close
the ~4-order-of-magnitude gap to representability on its own.

---

## 4. Step 4 — per-claim representability, honestly (not forced)

**No cell — no subject, no claim, no budget, across all 18 (3 subjects ×
2 claims × 3 budgets) combinations measured — reaches the 1-basis-point
representability floor.** The closest: **Signal, subject 1, B=5%:
0.133 bp**, still ~7.5× short of the 1 bp threshold.

**This contradicts the a priori expectation stated in the task** ("fast
claims may remain inexpressible... slow drift claims may become
expressible"). In this data, it is **Signal (the fast claim) that comes
closer to representability**, not Calibration. The mechanism: Signal's
measured mean episode+gap cycle (≈70–77 windows) is *larger* than
Calibration's in 2 of 3 subjects (≈37–53 windows) — a larger cycle length
means *fewer* episodes per session (`N_onsets = fT / cycle`), and a
smaller `N_onsets` means a *larger* `α_episode = B / N_onsets`. Signal's
longer average spacing between its (shorter) episodes outweighs
Calibration's higher episode count, and ends up producing the larger,
closer-to-representable α. Reported exactly as measured, not adjusted
toward the anticipated direction (task: "the autocorrelation measurement
decides the event model, not the desired outcome").

Subject 2's Calibration is a partial exception (mean episode length
44.174 windows — much longer isolated drift episodes than subjects 1/3,
whose Calibration episodes are short and frequent) — cross-subject
variability that a single-subject investigation would have missed;
another reason not to force a uniform per-claim verdict.

**No per-claim mix reaches Option A.** The honest answer, stated flatly:
**every measured (claim, budget) combination is Option B.**

---

## 5. Step 5 — config-side precision fix

Since §4 shows a genuine residual mismatch for every tested combination,
per the task's Step 5 gate, this section proposes a fix.

**Status update (implemented and validated as a follow-on task, not part
of this investigation's own deliverables):** the proposal below was
implemented as a NEW versioned config format, `config/eis.v1.json`
(`eis_schema_version: 1`, ppb-scaled), rather than as the in-place
`eis.v0.json` mutation this section originally sketched — `config/eis.v0.json`
was left byte-identical throughout. `trust_kernel/bands.py`'s
`validate_roc_points`/`derive_thresholds`/`load_eis_config`/
`validate_eis_config` were generalized to detect and dispatch on format
(`bp` vs `ppb`) rather than hardcoding `BP_SCALE`, with the `bp` codepath
confirmed byte-behaviorally unchanged (206/206 pre-existing pure-core
tests unaffected; original `harnesses/mutation_check.py` still 61/61).
Sufficiency was confirmed across all 18 (not just the closest) subject x
claim x budget combinations from this document's §3/§4 — every required
episode-based α (range 1.30e-7 .. 1.33e-5) is representable in ppb with
130x-13300x margin; none are representable in bp. Full validation:
`experiments/eis_v1_precision_validation.py`,
`artifacts/eis_v1_precision_validation_report.json`, new tests in
`tests/test_bands.py` (`DetectRateFormatTests`, `EisV1ConfigTests`,
`RepresentableAtScaleTests`), and a dedicated mutation harness,
`harnesses/mutation_check_eis_v1.py` (8/8, 100%), targeting the new
format-detection and scale-dispatch branches specifically. This is still
a REPRESENTATION fix only — `config/eis.v1.json` carries the same
placeholder 5%/5% synthetic ROC as `eis.v0.json`, just widened; no real
ROC threshold was derived by this change, and Phase 9 has not started.

**Proposal:** extend `config/eis.v0.json`'s rate representation from
integer basis points (`fpr_bp`, `tpr_bp`, scale 10⁴, minimum nonzero rate
10⁻⁴) to a wider fixed-point scale — e.g. **parts-per-billion**
(`fpr_ppb`, `tpr_ppb`, scale 10⁹, minimum nonzero rate 10⁻⁹) — sufficient
to represent the smallest episode-counted α found here (~10⁻⁷, subject 1
Calibration @ B=0.1%) with margin, and the smallest per-window α (~3×10⁻⁹,
independent of episode-counting) as well. `alpha_bp`/`beta_bp` in
`config/eis.v0.json` and the ROC point fields in
`trust_kernel.bands.validate_roc_points`/`derive_thresholds` would need
the same widening.

**Why this stays out of the frozen crypto path (CLAUDE.md §18's
escalation gate for §3/§4/§6/§9, not triggered by this proposal):**
`config/eis.v0.json` is **hashed config** (`roc_config_hash`), consulted
by the kernel to derive `θ1`/`θ2`/`band_cap` at load time — it is never
part of a **signed wire statement** (CLAUDE.md §8's frozen schema:
`{schema_version, key_id, source_id, boundary, claim_type,
raw_measurement, window_id, window_hash?, claimed_at, sig}`) or the
**verdict**'s signed fields. `raw_measurement` itself (the one
fixed-point quantity that *does* cross the wire) is untouched by this
proposal — only the **config-side threshold-derivation arithmetic**
changes scale. No statement field changes shape, no verdict field
changes shape, `canon.py`'s CBOR encoding is untouched, `sign.py`'s
Ed25519 rule set is untouched.

**Scope of what would need re-deriving if adopted:** `roc_config_hash()`
changes (a config format change, expected — every historical verdict
already commits to the specific config hash it was computed under, so
this is not a retroactive reinterpretation risk); `trust_kernel/bands.py`'s
`validate_roc_points`/`derive_thresholds` need their `BP_SCALE` constant
generalized or parameterized; every existing test referencing
`fpr_bp`/`tpr_bp`/`BP_SCALE` would need updating. This is exactly the
kind of change CLAUDE.md §18 asks to be written up before being made, not
a decision this investigation is authorized to make.

---

## 6. Deliverables summary

- **Formal event model** (§1): raw claim measurement is a real-valued,
  temporally autocorrelated process (lag-1 ≈ 0.7–0.8), not i.i.d. per
  window. Falsification test defined in advance; **not falsified**, in
  any of 12 measured cells, at either of two independent operating
  points. Architectural case for episode-counting stands regardless;
  practical case is empirically supported, not merely asserted.
- **Both availability derivations, side by side** (§3): per-window
  formula reproduces Phase 8.5 exactly; episode formula improves α by
  1–2 orders of magnitude, exactly matching the measured episode/gap
  cycle length.
- **Per-window vs. episode α table** (§3): given above for all three
  budgets.
- **Per-claim representability** (§4): **none representable**, in any of
  18 combinations. The anticipated fast/slow asymmetry did not hold in
  the direction expected; reported as measured.
- **Mutation kill rate on new code:** `event_model/`
  (`harnesses/mutation_check_event_model.py`): **12/12 (100%)**. Pure-core
  suite confirmed unaffected: **61/61 (100%)**.

### Recommendation

**Option B for every measured (subject, claim, budget) combination:**
episode-counting is empirically justified (§1) and materially improves α
(§3) — the SBA per-window formulation is not invalidated by this finding,
it is *augmented*: independence across windows genuinely does not hold,
but Phase 8.5's CTPR-idempotence result is a separate, still-valid
finding about the *union* structure, not the *temporal* structure, and is
unaffected by anything measured here. Neither formulation, at any tested
illustrative budget, is representable at the current basis-point config
granularity — a real, config-side numeric-precision gap, **not** a CTPR
gap and **not** resolved by switching to episode-counting alone. Do not
proceed to Phase 9's real ROC/threshold derivation on the current
`config/eis.v0.json` rate representation; the §5 proposal (or an
equivalent) needs PI review and a separate implementation pass first.

CLAUDE.md is unmodified by this investigation.
