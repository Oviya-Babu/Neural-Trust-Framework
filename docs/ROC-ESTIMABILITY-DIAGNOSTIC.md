# ROC-Estimability Diagnostic — Phase 9 Cohort Decision and the Tail-Floor Rule

Status: diagnostic report. NOT Phase 9 — no real ROC threshold was derived
by either run below, `calibration_status` was never flipped to `measured`,
and no θ1/θ2/band_cap value was read off or inspected. Both runs enforce
the same ephemerality guarantee: every threshold/FPR/TPR-location
computation is structurally confined to two private helpers in
`roc_estimability/stability.py` (`_low_tail_threshold`, `_fpr_tpr_at`)
whose return values are never propagated by any public function's return
value, verified by 13/13 mutation kill rate targeting that exact boundary,
plus a runtime guard (`_assert_no_forbidden_keys`) that walks each report
before it is written and aborts if a numeric value ever lands under a
threshold-shaped key.

This document consolidates two runs:
- **Run 1** (`experiments/roc_estimability_diagnostic.py`): all six claims,
  held-out {4,5,6,7,8,9} vs. full 9-subject pool.
- **Run 2 / Part 1** (`experiments/calibration_full9_sufficiency.py`):
  Calibration only, full 9-subject pool against its own scaled bar, gating
  whether Calibration gets a clean cohort-size resolution or falls under
  the Tail-Floor Rule.

Raw sanitized reports: `artifacts/roc_estimability_diagnostic_report.json`,
`artifacts/calibration_full9_sufficiency_report.json`.

## 1. Method summary

Real Phase 8 producers, real BCIC IV 2a data, all 9 subjects (`bci_pipeline.pipeline.run_subject`
per subject; `bci_pipeline/` and `sensors/` are not modified). Per claim,
honest/attack samples are constructed behaviourally (CLAUDE.md §3), never
by direct trust injection:

- **Signal** (REAL): honest = `measure_signal_quality()` on each real
  session-E trial's raw epoch. Attack = the same real epoch with a 50 Hz
  line-noise sine injected at 3× that epoch's own per-channel std (fixed,
  data-adaptive, pre-committed — not tuned per subject).
- **Calibration** (REAL): honest = `measure_calibration_drift()` against
  the subject's own session-T enrollment stats. Attack = the same real
  session-E features against a *different* subject's enrollment stats — a
  genuine cross-subject session-mismatch condition, zero synthetic
  injection. Foil pairing is fixed before running: subject *s*'s foil is
  *s*+1, wrapping 9→1.
- **Model** (EMULATED_PROTOCOL): honest/attack = the three Phase 8 attack
  cases (bit-flipped weights, stripped signature, unsigned substitute)
  applied to each subject's own real trained classifier artifact.
- **Device, FSI** (EMULATED_PROTOCOL): real DTLS handshake / real swtpm
  quote outcomes, measured once via a modest number of real repeats (not
  per subject — the protocol does not depend on EEG subject identity) and
  replicated across every subject's record, disclosed as such.

Per-claim metrics (all via `roc_estimability/stability.py`'s public API):
class presence/separation, subject-level bootstrap (resample subjects with
replacement, N=1000, evaluated at the smallest empirically resolvable
low-FPR threshold — the closest real-data proxy for "the operating region
the swept budgets imply," see §3), leave-one-subject-out swing, and a
cohort-stability-gap ratio. A claim is sufficient on a cohort iff all
three pre-committed bars clear: ≥4/6 (or the scaled equivalent) subjects
separating, ≤2× band-width ratio vs. the reference pool, ≤0.15 LOSO swing.

## 2. Run 1 results — held-out {4-9} vs. full-9, all six claims

| Claim | Held-out class support | Held-out verdict | Failed tests |
|---|---|---|---|
| Signal | 5/6 separating | Insufficient | `loso_tpr_swing` (max swing 1.0 — the theoretical maximum) |
| Calibration | 3/6 separating | Insufficient | `class_support`, `bootstrap_band_ratio_fpr` (∞), `bootstrap_band_ratio_tpr` (2.6×) |
| Model | 6/6 separating | Sufficient | none |
| Device | 6/6 separating | Sufficient | none (subject-invariant by construction) |
| FSI | 6/6 separating | Sufficient | none (subject-invariant by construction) |
| ActuationFidelity | — | Not assessed | no offline per-subject measurement exists (needs a live enforcement pass) |

Signal's failure is notable for being a **sample-size floor, not a
cohort-composition problem**: its bootstrap TPR band width at the low-tail
proxy region is 1.0 (the full possible range) on *both* the held-out-6
*and* the full-9 pool. Adding subjects does not shrink it — a single
subject's presence/absence still swings the estimate across its entire
range regardless of cohort size at this diagnostic's measurement
granularity (§3).

Calibration's failure is a **class-support** problem: only half the
held-out subjects show genuine drift separation under the cross-subject
mismatch attack.

## 3. Run 2 / Part 1 — Calibration, full 9-subject pool

Question: does adding subjects 1-3 (not in the held-out cohort) push
Calibration's class-support count over its own bar, scaled to 9 subjects
(6/9, the same 2/3 proportion as 4/6 — not a loosened count)?

**Measured, not assumed:**
- Class support: **5/9 separating** (up from 3/6 = 50% to 5/9 = 55.6% —
  a real but insufficient improvement). Sufficiency floor: 6/9.
- Subjects added by the full pool: subject 1 separates, subject 2 does
  **not**, subject 3 separates (2 of the 3 new subjects).
- All 9 subjects individually: {1: separates, 2: no, 3: separates,
  4: separates, 5: no, 6: separates, 7: no, 8: no, 9: separates}.
- Bootstrap band width at full-9 (two independent runs, different seeds):
  **0.0 / 0.0** for both FPR and TPR — the tail estimate is perfectly
  stable at full-9 (order-statistic variance genuinely shrinks with N
  here, consistent with extreme-value-theory expectations).
- Self-comparison ratio (run A / run B): undefined (0/0 — both runs are
  exactly stable, so the ratio has no denominator to divide against).
- LOSO swing at full-9: **0.0 / 0.0** — no single subject (of 9) swings
  the estimate at all.
- **Verdict: `sufficient_on_held_out=False`, failed_tests=['class_support']`.**

**Disposition: Calibration does NOT get a clean cohort-size resolution.**
The bootstrap-width and LOSO criteria are perfectly satisfied at full-9 —
more subjects genuinely stabilized the *tail estimate*. But the
*class-support* bar (whether the attack condition is distinguishable from
honest operation at all, for enough subjects) did not clear, even at the
largest cohort this dataset offers. Calibration falls under the Tail-Floor
Rule (§4) on the same footing as Signal, via the class-support trigger
specifically, not the tail-instability trigger Signal hit.

## 4. Tail-Floor Rule

Evaluated independently per (claim, budget) pair across the three swept
budgets {0.1%, 1%, 5% per 8h}. A claim's threshold (θ1 or θ2) at a given
budget triggers the Tail-Floor Rule when its operating point fails to be
stably resolvable by these fixed bars: fewer than 4/6 (equiv. 6/9 at full
pool) subjects separating both classes at that point, OR bootstrap
band-width ratio > 2× vs. the full-pool reference, OR leave-one-subject-out
swing > 0.15. When triggered, the threshold is set to the most extreme
empirically resolvable operating point (tightest stably-supported point
the ROC reaches under these bars) and no tighter, reported as a
conservative floor ("no tighter than X"), not a point estimate, with the
sub-resolution region disclosed. No parametric tail model is fitted.
Triggering at one budget does NOT imply floor treatment at a looser budget
for the same claim — each (claim, budget) pair is evaluated on its own.
The rule applies identically to θ1 (low-FPR end) and θ2 (high-TPR/1−β
end); for any claim whose θ2 reaches TPR ≥ 1−β only within a tail region
failing these bars, θ2 falls under the rule with the same disclosure.
Justification: (a) no distributional assumption is introduced; (b) it
fails in the conservative direction — it cannot manufacture a permissive
threshold by extrapolating into unmeasured tail, consistent with the
architecture's fail-closed / missing-claim-reads-LOW discipline
(CLAUDE.md §10).

## 5. Measured resolution note — does the trigger actually differentiate by budget?

The rule text above evaluates each (claim, budget) pair independently, on
principle. This diagnostic checked, rather than assumed, whether its
*actual measured resolution* is fine enough to produce a differentiated
answer across the three budgets for Signal and Calibration — and it is
not, honestly reported here rather than silently defaulting to a
per-budget split that the data doesn't support.

Both diagnostic runs use real per-**trial** samples (~280 trials/subject,
~2,500 pooled at full-9 — subject 1 alone contributes 282 real session-E
trials), not the continuous per-**window** stream
(`docs/EVENT-MODEL-INVESTIGATION.md` used ~23,207 windows/subject for its
honest-operation measurement, but never built a continuous attack-class
stream). At trial-level granularity, the smallest empirically resolvable
nonzero rate is ~1/2,500 ≈ 4×10⁻⁴ (400,000 ppb). The three swept budgets'
episode-based per-claim α (from `docs/EVENT-MODEL-INVESTIGATION.md` §3-4)
top out, at the loosest budget (B=5%), around 1.33×10⁻⁵ (13,300 ppb) —
still **~30× below** the trial-level resolution floor. The tightest
budget (B=0.1%) is ~3,000× below it.

**Conclusion: at this diagnostic's measured resolution, all three swept
budgets are below the empirical resolution floor, uniformly.** The
Tail-Floor Rule, as actually triggered by Signal and Calibration in Runs 1
and 2, therefore applies at **all three swept budgets for both claims**,
not only the tightest. This is a measured finding, not an assumption that
the trigger propagates from tight to loose budgets — the arithmetic above
was checked directly. A budget-differentiated result (e.g. the loosest
budget clearing the bar while the tightest does not) would require
continuous per-window attack-class data, which does not currently exist
and was out of scope for this diagnostic pass.

## 6. Per-claim cohort and disclosure

| Claim | Cohort | Disposition |
|---|---|---|
| Model | held-out {4-9} | Sufficient — clean |
| Device | held-out {4-9} | Sufficient — clean (subject-invariant measurement, disclosed) |
| FSI | held-out {4-9} | Sufficient — clean (subject-invariant measurement, disclosed) |
| Signal | full 9-subject pool | Tail-Floor Rule at all three swept budgets (§5) — LOSO-tail trigger |
| Calibration | full 9-subject pool | Tail-Floor Rule at all three swept budgets (§5) — class-support trigger |
| ActuationFidelity | not assessed | out of scope (no offline per-subject measurement exists) |

**Estimation vs. representation — kept separate, not conflated:**
`config/eis.v1.json`'s ppb scale (docs/EVENT-MODEL-INVESTIGATION.md §5,
`experiments/eis_v1_precision_validation.py`) resolves whether a value can
be *represented* once known. The Tail-Floor Rule addresses a different
question: whether a value can be *estimated* from the data actually
available. Both are real, both are now handled, and solving one does not
solve the other — eis.v1 does not make Signal's or Calibration's tail
estimate any more stable; it only ensures that whatever value Phase 9 (or
the Tail-Floor Rule's conservative floor) eventually produces has
somewhere to be written down.

**Stable-label convention (updated after implementation traced the actual
hash coverage — see `docs/CLAUDE-MD-DIFF-SBA-FREEZE-APPLIED.md`'s
correction entry):** every θ1/θ2 Phase 9 derives carries a
`resolution_status ∈ {pending, stable, tail_floor}` label, per claim per
swept budget, implemented in `config/eis.v1.json` (not a reporting-only
convention as first drafted) and validated fail-closed by
`trust_kernel/bands.py`'s `validate_eis_config()`. It is therefore covered
by `roc_config_hash()` — confirmed directly: mutating only a
resolution_status value changes the hash
(`tests/test_bands.py:RocConfigHashCoversResolutionStatusTests`). This is
NOT a new wire/signed field — CLAUDE.md §8's frozen Statement/Verdict
schema is byte-identical (confirmed by source hash and AST inspection, not
asserted) — but it is also not silently editable: it is one of the
objects §8's existing six-config-hash discipline already protects
("editing a threshold, a scale, or rotating a key silently reinterprets
all history"). §9's crypto rule set is untouched; nobody in π's call path
reads this field.

Feasibility-region values and any Tail-Floor-Rule-derived threshold value
remain outputs of Phase 9, not pre-registered here — only the methodology
(event model, apportionment, β derivation, ppb representation, and now the
Tail-Floor Rule) is fixed by this document and by CLAUDE.md §20.

## 7. Mutation kill rate and regression

`roc_estimability/` mutation harness: 13/13 (100%), including the two new
mutants covering the generalized `min_subjects_separating` parameter added
for this full-9 self-check. Pure core (`tests/`): 223/223 unaffected.
`tests_roc_estimability`: 40/40. CLAUDE.md was not modified by either
diagnostic run itself (only by the separate, explicit freeze pass this
document's findings feed into).
