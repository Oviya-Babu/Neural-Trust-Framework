# Proposed CLAUDE.md diff — SBA methodology freeze (§20/§28)

**SUPERSEDED — APPLIED, in an expanded form, by a later pass. This
document is kept as a historical record of the first (unapplied) draft;
it did not include the ROC-estimability diagnostic or the Tail-Floor Rule,
neither of which existed yet when this was written. The version that was
actually applied to CLAUDE.md — §20 expanded with the Tail-Floor Rule,
the measured per-claim cohort assignment, and the stable-label convention,
plus §28 extended to cover Tail-Floor-Rule conservative floors — is
recorded in `docs/CLAUDE-MD-DIFF-SBA-FREEZE-APPLIED.md`. CLAUDE.md's md5
changed from `bd3990f25199177fd5d5bbfb6cce539b` (the hash noted below,
current when this draft was written) to `065e8649b7a0fdf71f400823da5a3576`
(current after the applied pass) — confirmed to differ only by the
changelog line, the §17 pointer, and the new §20/§28 sections.**

Original draft below, unmodified, for reference only:

**NOT APPLIED [at the time this was written]. CLAUDE.md on disk is unchanged (md5 `bd3990f25199177fd5d5bbfb6cce539b`,
confirmed at the time this diff was drafted). This file is the review
artifact; the PI applies it (or amends it) by hand.**

Three changes, all additive except one line in §17. Nothing in §3
(threat model), §4 (trust model), §6 (enforcement), or §9 (crypto rules)
is touched — no CLAUDE.md §18 escalation is triggered by content, though
this whole pass is itself the PI-directed escalation for the record.

Numbering note: §19 and §21–§27 do not exist yet. §20 and §28 are used
here because `docs/PHASE8.5-SBA-VALIDATION.md` §6 already reserved those
two numbers for exactly this content ("Add to §20/§28 ... this diff
assumes they will be created when/if SBA methodology is formally adopted
into the spec"). This diff does not fill in 19 or 21–27; that gap is
deliberate and should be confirmed by the PI, not silently resolved here.

---

## 1. Changelog line (top of file, after the existing two changelog lines)

```
Changelog: 2026-07-20 — SBA (Session Budget Allocation) methodology frozen: new §20 (α/β — event model, apportionment, β derivation, ppb representation) and §28 (illustrative-budget scope guard); supersedes the provisional §17 α/β point-value text (§17 updated to a SETTLED pointer, dataset-entry style).
```

## 2. §17 — replace the α/β bullet

**Before:**
```
α and β. Provisionally 0.05/0.05. Policy, not measurement. My standing recommendation: α tighter (≈1e-3; at 10 Hz, α=0.05 per claim per window is ~30 spurious halts/minute), β looser (≈0.10, because T5 — not β — is the safety bound). Report the feasible region, not point values. The paper must derive the per-session halt rate from the per-window α explicitly.
```

**After:**
```
α and β — SETTLED (methodology; see §20 and §28). The event model, apportionment formula, β-derivation approach, and ppb representation are fixed and pre-registered (docs/OSF-PREREGISTRATION.md, not yet submitted). Illustrative budget VALUES remain a swept feasible region, not point-derived; real per-claim thresholds remain Phase 9's output, not this decision's.
```

This mirrors the existing "Dataset — SETTLED (BCIC IV 2a, see dataset
entry, §17a)." bullet already in §17 — same pattern, second use.

## 3. New §20 (insert after §18, before the `## Environment & Workspace Rules` block)

```
20. α and β — final SBA (Session Budget Allocation) methodology (supersedes the provisional §17 entry)

Event model. A spurious session restriction is counted as an episode: a maximal run of below-Normal verdicts, with adjacent runs merged under a pre-committed debounce rule D = the 5th percentile of the measured inter-restriction gap distribution (smallest D such that ≥5% of measured gaps are ≤ D), fixed before assessing whether merging changes representability. The naive per-window formulation (windows treated as independent Bernoulli trials) is empirically falsified, not merely disfavoured: real honest-operation continuous EEG across 3 subjects (BCIC IV 2a, session E) measured lag-1 autocorrelation of the restriction indicator at 0.67–0.82 and restricted-run lengths 3–31× the length an independent-draw process would produce, for both Signal and Calibration claims at both tested operating points. See docs/EVENT-MODEL-INVESTIGATION.md for the full falsification protocol and results.

α. Swept over three illustrative session-availability budgets B ∈ {0.1%, 1%, 5% per 8h}, reported as a feasible region rather than a point value. These are illustrative research parameters, not deployment requirements — this project has no target clinical deployment or stakeholder to source a budget from (§28), the same status the reference Env/Ceil values in §14 already carry. Each budget is apportioned to per-claim α via the flat formula (α applied unmodified per claim, undiscounted for CTPR propagation): proven exact, not assumed, for the deployed DAG by exhaustive 729-combination enumeration (docs/PHASE8.5-SBA-VALIDATION.md) — CTPR has zero effect on P(Verdict=Safe) under same-severity propagation, which covers every edge in the current DAG (FSI→Signal, FSI→Model). The propagation-aware correction (ancestor-closure formula, already derived) is shelved, not discarded: it must be re-applied if any future CTPR edge runs from a lenient parent to a strict child — the one topology that breaks the exactness proof. Representation: eis.v1 (ppb, below) is required before any of these budgets' derived per-claim α is representable at all; eis.v0's basis-point scale cannot hold any of them (docs/EVENT-MODEL-INVESTIGATION.md §4).

β. Per-dimension (strict dimensions and the lenient dimension, Device, derived separately), consequence-exposure-derived rather than globally hand-set. A PFD_enforcement (probability of failure on demand of the enforcement path) basis is rejected: deterministic enforcement has no probability of failure on demand under A_data — P(x ⊓ Ceil > Ceil) = 0 exactly, by the meet axiom underlying T5, not by measurement — so a PFD-style β would be circular and would additionally imply an unclaimed SIL rating (§1: "Never claimed: ... SIL certification"). If the underlying consequence-exposure budget is itself unsourced (no clinical/engineering standard to anchor it to, the same gap α's session-availability budget has), it receives the identical illustrative-sweep treatment as α — a feasible region, not a point value.

Note (methodological contribution, not implementation detail): deriving β from a consequence-exposure budget is possible only because T5 severs β from the hazard probability — the enforcement bound holds regardless of β, so β can be set from consequence exposure without β itself having to certify safety. A system without T5's independent consequence bound could not derive β this way; it would need β to BE the safety case, which is exactly the SIL-certification claim this project explicitly disclaims.

Representation. Thresholds, α, and β are carried in the ppb-scaled config format (config/eis.v1.json, eis_schema_version 1), proven sufficient with margin across all 18 (subject × claim × budget) combinations measured by the event-model investigation (minimum margin 130×; none of the 18 are representable at eis.v0's basis-point scale). This is a representation-only change: config/eis.v0.json is untouched, roc_config_hash and the interpretation-layer formula are unchanged in effect, and the wire/signed-statement/crypto path (§8, §9) is byte-identical before and after — confirmed by source hash and AST inspection, not asserted.

Pre-registration: docs/OSF-PREREGISTRATION.md (draft, not submitted). §13's rule applies: a git timestamp is not pre-registration.
```

## 4. New §28 (insert after existing content — placement TBD by the PI given §21–§27 don't exist yet; content only, not a position claim)

```
28. Scope guard — illustrative budgets and the absence of a clinical stakeholder

The session-availability budget governing α, and the consequence-exposure budget governing β (§20), are illustrative research parameters rather than deployment requirements. In the absence of a target clinical deployment or stakeholder, illustrative budget values are evaluated parametrically — swept over a feasible region — in the same manner as the reference Env/Ceil values in §14. The methodology for deriving α and β from a budget is what is pre-registered (§20; docs/OSF-PREREGISTRATION.md), not any particular budget value; adopting this architecture for a specific deployment requires sourcing real budgets from that deployment's clinical/engineering stakeholders and re-running the same, already-fixed, methodology.
```

---

## What this diff does NOT do

- Does not touch §3, §4, §6, §9 (FROZEN sections under §18's escalation gate).
- Does not derive, sweep, or hand-set any real α/β number — §20/§28 are
  methodology text, matching the "reference values, not prescriptions"
  framing already used for Ceil/Env (§6) and the milestone table (§14).
- Does not submit anything to OSF. `docs/OSF-PREREGISTRATION.md` is
  submission-ready text, not a submission.
- Does not start Phase 9 or derive any real ROC threshold.
