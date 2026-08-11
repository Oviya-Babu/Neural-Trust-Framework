# OSF Pre-registration — SBA (Session Budget Allocation) methodology

**Status: DRAFT, prepared for PI review. NOT submitted to OSF. No git
timestamp on this file substitutes for pre-registration (CLAUDE.md §13: "A
git timestamp is not pre-registration — history is rewritable and
reviewers know it."). This document is submission-ready text only; actual
registration is a PI action on the OSF platform, before Phase 9 begins.**

This corresponds to the CLAUDE.md §20/§28 freeze, which has been APPLIED
(CLAUDE.md hash confirmed to have changed only by the freeze itself — see
`docs/CLAUDE-MD-DIFF-SBA-FREEZE-APPLIED.md`). Nothing in this document
derives a real ROC threshold; Phase 9 has not started.

---

## 1. What is being pre-registered

The **methodology** that will convert an illustrative session-availability
budget into per-claim α and β values once Phase 9 supplies real ROC
curves — not any particular budget value, and not any threshold. This
follows the same "reference values, not prescriptions" pattern CLAUDE.md
§6 already applies to Ceil/Env, and §14 applies to the milestone table:
label the parameters as illustrative, fix the *procedure* that acts on
them.

**Explicitly NOT pre-registered** (these are Phase 9 outputs, decided
after real ROC data is seen, and would corrupt the pre-registration if
fixed in advance):
- Per-claim ROC curves.
- Derived θ1/θ2/band_cap values for any claim.
- The `calibration_status: measured` transition.
- Any accuracy/AUC figure (already out of scope per CLAUDE.md §17a: "its
  decoding accuracy is explicitly not a result").

## 2. Fixed prior to seeing any real ROC data

### 2.1 The three illustrative session-availability budgets

B ∈ {0.1%, 1%, 5%} per 8-hour session. This is the fixed set. No budget
value outside this set may be added, and none of the three may be dropped,
after Phase 9's ROC data is seen. Reported as a feasible region across all
three, not a single point estimate (CLAUDE.md §17's original instruction,
carried into §20).

### 2.2 Event model

A spurious session restriction is counted as an **episode**: a maximal run
of below-Normal verdicts. Adjacent runs are merged under a **pre-committed
percentile debounce rule**: D = the 5th percentile of the measured
inter-restriction gap distribution (the smallest D such that at least 5%
of measured gaps are ≤ D). The percentile (5%) was fixed before the gap
distribution was inspected for whether it would favor the episode or the
per-window formulation.

**Falsification record (already observed, disclosed transparently, not
itself a pre-registered claim — see §3 below for why this doesn't corrupt
the pre-registration):** the competing per-window formulation (each 100ms
window treated as an independent Bernoulli trial) was tested against real,
honest-operation, continuous EEG from BCIC IV 2a subjects 1–3 (session E,
~23,207 windows/subject) and found empirically falsified, not merely
disfavored — lag-1 autocorrelation of the restriction indicator measured
0.67–0.82 (falsification bound: 0.05) and restricted-run lengths measured
3–31× the length an independent-draw process would produce, consistently
across all 3 subjects, both Signal and Calibration claims, and both tested
operating points (5%, 1%). Full protocol, mechanical falsification
criterion, and per-subject numbers: `docs/EVENT-MODEL-INVESTIGATION.md`.

### 2.3 Apportionment formula (session budget → per-claim α)

A **flat** formula: the session budget B is converted to a per-claim α
without any CTPR-propagation discount or correction. This is not an
assumption of convenience — it is **proven exact** for the deployed
architecture by exhaustive enumeration of all 3^6 = 729 lattice
combinations (`docs/PHASE8.5-SBA-VALIDATION.md`): CTPR has exactly zero
effect on P(Verdict = Safe) under same-severity propagation, which is what
every edge in the current CTPR DAG (FSI→Signal, FSI→Model) is.

**Standing re-check trigger, pre-registered alongside the formula itself:**
if any future CTPR edge runs from a lenient parent (Device) to a strict
child, the exactness proof no longer applies (a "severity escalation"
case, quantified in `docs/PHASE8.5-SBA-VALIDATION.md` §1.5), and the
already-derived ancestor-closure correction formula
(`sba_validation/probability_model.py:corrected_p_safe_with_ancestor_closure`)
must be substituted for the flat formula before any α is apportioned under
that topology. This substitution is itself fixed in advance, not a
post-hoc decision.

### 2.4 β derivation

**Per-dimension**, not global: strict dimensions (Signal, Model,
Calibration, FSI, ActuationFidelity) and the lenient dimension (Device)
receive separate β derivations, both **consequence-exposure-derived**
rather than hand-set.

**Rejected basis, fixed in advance:** a PFD_enforcement (probability of
failure on demand of the enforcement path) formulation is rejected. Under
Position A, deterministic enforcement has no probability of failure on
demand: P(x ⊓ Ceil > Ceil) = 0 exactly, by the meet axiom underlying T5,
not by measurement. A PFD-style β would therefore be circular (deriving a
probability from a quantity that is provably always zero) and would
additionally imply an unclaimed SIL rating (CLAUDE.md §1: "Never claimed:
... SIL certification").

**If the consequence-exposure budget itself is unsourced** (no
clinical/engineering standard available to anchor it to — the same
sourcing gap α's session-availability budget has, per §2.7/§28), it
receives the **identical illustrative-sweep treatment as α**: a feasible
region across illustrative values, not a single point-derived number.

**Why this is a methodological contribution, fixed here rather than left
open:** deriving β from consequence exposure is only possible because T5
severs β from the hazard probability — the enforcement bound (§6) holds
regardless of what β is set to, so β does not have to certify safety by
itself. A system without T5's independent, verdict-independent consequence
bound could not use this derivation; it would need β to constitute the
safety case, which is exactly the SIL-certification claim this project
explicitly disclaims (CLAUDE.md §1).

### 2.5 Representation

Thresholds, α, and β are carried in a parts-per-billion fixed-point config
format (`config/eis.v1.json`, `eis_schema_version: 1`, scale 10⁹),
introduced specifically because the basis-point format (`config/eis.v0.json`,
scale 10⁴) cannot represent any of the 18 (subject × claim × budget) α
values the event-model investigation measured (range 1.30×10⁻⁷ ..
1.33×10⁻⁵; minimum nonzero basis-point rate is 10⁻⁴). Confirmed
sufficient with margin (minimum 130×) across all 18, not just the closest
case (`artifacts/eis_v1_precision_validation_report.json`). This is a
representation change only: `config/eis.v0.json` is untouched, and the
wire/signed-statement/crypto path (CLAUDE.md §8, §9) is byte-identical
before and after (source-hash and AST-checked, not merely asserted).

### 2.6 Tail-Floor Rule

Evaluated independently per (claim, budget) pair across the three swept
budgets (§2.1). A claim's threshold (θ1 or θ2) at a given budget triggers
the Tail-Floor Rule when its operating point fails to be stably resolvable
by these fixed bars: fewer than 4/6 (equiv. 6/9 at full pool) subjects
separating both classes at that point, OR bootstrap band-width ratio > 2×
vs. the full-pool reference, OR leave-one-subject-out swing > 0.15. When
triggered, the threshold is set to the most extreme **empirically
resolvable** operating point (tightest stably-supported point the ROC
reaches under these bars) and no tighter, reported as a **conservative
floor** ("no tighter than X"), not a point estimate, with the
sub-resolution region disclosed. No parametric tail model is fitted.
Triggering at one budget does NOT imply floor treatment at a looser budget
for the same claim — each (claim, budget) pair is evaluated on its own.
The rule applies identically to θ1 (low-FPR end) and θ2 (high-TPR/1−β
end); for any claim whose θ2 reaches TPR ≥ 1−β only within a tail region
failing these bars, θ2 falls under the rule with the same disclosure.

**Justification, fixed in advance:** (a) no distributional assumption is
introduced; (b) it fails in the conservative direction — it cannot
manufacture a permissive threshold by extrapolating into unmeasured tail,
consistent with the architecture's fail-closed / missing-claim-reads-LOW
discipline (CLAUDE.md §10).

**Measured, not assumed, whether the trigger differentiates by budget:** a
dedicated diagnostic (`docs/ROC-ESTIMABILITY-DIAGNOSTIC.md`) checked this
directly rather than relying on the rule's per-(claim,budget) framing to
imply a differentiated result. At the diagnostic's real per-subject trial
counts (~280/subject, ~2,500 pooled at full-9), even the loosest swept
budget's implied operating region sits ~30× below the smallest empirically
resolvable rate (~1/N_pooled). **Result: the Tail-Floor Rule, as measured
for Signal and Calibration (§5), fires at all three swept budgets for both
claims — not only the tightest.** A budget-differentiated result would
require continuous per-window-granularity attack-class data, which does
not exist yet for either claim's attack condition; this is disclosed as a
current limitation, not resolved by assumption.

**Stable-label convention (implemented, not just described — corrected
after tracing the actual hash coverage):** every θ1/θ2 Phase 9 derives
under the Tail-Floor Rule carries a `resolution_status ∈ {pending, stable,
tail_floor}` label, per claim per swept budget, in `config/eis.v1.json`,
validated fail-closed by `trust_kernel/bands.py`, and therefore covered by
`roc_config_hash()` — demonstrated directly by mutating a resolution_status
value and observing the hash change. This is not a new wire/signed field
(CLAUDE.md §8's frozen Statement/Verdict schema is byte-identical), but it
is not silently editable either: it is protected by the same six-config-hash
discipline §8 already applies to every other config value. §9's crypto rule
set is untouched; the label is consulted by nobody in π's call path.

### 2.7 Scope condition this pre-registration is filed under

There is no target clinical deployment or stakeholder for this project
(CLAUDE.md §17a: "venue target remains CPS/security, not a clinical
journal"). In that absence, every budget value above (§2.1's three B
values, and §2.4's consequence-exposure budget if likewise unsourced) is
evaluated **parametrically** — as an illustrative sweep — in the same
manner CLAUDE.md §14 already treats the reference Env/Ceil values. This
pre-registration binds the **methodology**; it does not assert that any
swept value is a deployment recommendation.

## 3. Why using subjects 1–3 to establish the event model does not corrupt
   this pre-registration

The event model (§2.2) was derived from real EEG (BCIC IV 2a, subjects
1–3) via a mechanical, pre-stated falsification criterion (lag-1
autocorrelation < 0.05 AND run-length ratio in [0.8, 1.5], both required
— `docs/EVENT-MODEL-INVESTIGATION.md`), not tuned toward a preferred
conclusion; the task that produced it was explicitly gated against exactly
that failure mode ("Do not let a marginal or weak result get absorbed into
the predicted episode-based conclusion"). This is the same role a pilot
study plays ahead of a confirmatory pre-registered study: it may inform
which analysis method is fixed, provided the method itself is then fixed
*before* the confirmatory data (Phase 9's real per-claim ROC, not yet
computed for any subject, on any subject) is seen. Phase 9's ROC
derivation is the confirmatory step this pre-registration protects; the
event-model investigation is disclosed here in full rather than treated as
if it hadn't happened, which is what makes this pre-registration
falsifiable rather than decorative.

## 4. What Phase 9 is committed to, once this is registered

Given a budget B ∈ {0.1%, 1%, 5%}, Phase 9 must:
1. Compute per-claim α by the flat formula (§2.3), substituting the
   ancestor-closure correction only if the standing re-check trigger has
   fired (it has not, for the current DAG).
2. Compute per-dimension β by the consequence-exposure derivation (§2.4),
   never by a PFD_enforcement formulation.
3. Express both in `config/eis.v1.json`'s ppb representation (§2.5).
4. Derive θ1/θ2/band_cap from real, measured ROC via the existing,
   unmodified `derive_thresholds()` formula (CLAUDE.md §4) — never
   hand-assigned (CLAUDE.md §11, §15).
5. Report the per-claim ROC distribution honestly, including any claim
   whose ROC does not clear the required TPR (structurally capped at
   band_cap = MED, CLAUDE.md §4) — not cherry-picked, not re-run with
   adjusted α/β after observing AUC (CLAUDE.md §15).

None of steps 1–5 has been performed by this document. This document fixes
*how* they will be performed.

## 5. Per-claim cohort assignment (measured, §2.6's diagnostic)

| Claim | Cohort Phase 9 must use | Basis |
|---|---|---|
| Model | held-out {4,5,6,7,8,9} | Sufficient: 6/6 class separation, 0-width bootstrap band, 0 LOSO swing |
| Device | held-out {4,5,6,7,8,9} | Sufficient: same, subject-invariant measurement (disclosed, not independent per-subject variability) |
| FSI | held-out {4,5,6,7,8,9} | Sufficient: same as Device |
| Signal | full {1..9} | Insufficient on held-out (LOSO TPR swing = 1.0, the theoretical maximum); full-9 pool equally unstable at the same tail proxy — a sample-size floor, not fixed by cohort size. Tail-Floor Rule applies at all three swept budgets (§2.6). |
| Calibration | full {1..9} | Insufficient on held-out (3/6 separating) AND on full-9 (5/9 separating, below the 6/9 floor) — adding subjects 1-3 helped (2 of 3 separate) but did not clear the bar. Bootstrap width and LOSO swing are both 0 at full-9 (genuinely stabilized), so this is a class-support failure specifically, not a tail-instability one. Tail-Floor Rule applies at all three swept budgets (§2.6). |
| ActuationFidelity | not assessed | No offline per-subject measurement exists under honest, no-live-enforcement-loop operation; out of scope for this diagnostic. |

This cohort assignment is itself pre-registered (Phase 9 must not
re-litigate it after seeing ROC data); the specific θ1/θ2 values Phase 9
derives on each cohort, and any Tail-Floor-Rule conservative floor, are
not (§1's exclusion list).
