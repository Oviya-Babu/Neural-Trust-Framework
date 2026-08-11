# Results

Status: **consolidated results section.** Every number below is sourced from
a specific artifact/manifest pair under `artifacts/` and `provenance/`, not
retyped from memory — the cited path is the regeneration entry point per
CLAUDE.md §13 ("no figure enters the dissertation that cannot be regenerated
from its manifest by one command"). Phase-by-phase; see `docs/EIS-v1.md`,
`docs/ENFORCEMENT-v1.md`, `docs/THREAT-MODEL.md` for the conceptual layer
these numbers instantiate, and `docs/LIMITATIONS.md` for what they do not
establish.

## Phase 2 — kernel core (conformance)

- Floor-dominance table: 6 dimensions × 3 levels, exhaustively checked against
  `crit_table.json`. `artifacts/phase2_floor_dominance.json` /
  `provenance/phase2_kernel_core_manifest.json`.
- CTPR propagation: **18/18** cases match `effective_child = meet(child,
  g(FSI))` exactly. `artifacts/phase2_ctpr_table.json`.
- Labelled per CLAUDE.md §12: machine-checked implementation conformance
  (⊓-of-monotone-maps-is-monotone is a theorem; this fails only on a dict
  typo), not independent empirical validation.

## Phase 3 — T4 statement admission

- 6 failure-mode cases (invalid signature, unsupported schema, unauthorised
  source, window_id mismatch, late arrival, plus the healthy baseline), fixed
  verification order (§10), every failure routes to that dimension reading
  LOW, never "record absent." `artifacts/phase3_t4_failure_modes.json`.

## Phase 4 — evidence log / replay

- Tamper-evidence: a mid-chain entry tampered, `first_broken_seq` correctly
  identified, every subsequent entry (not just the tampered one) reported
  broken. `artifacts/phase4_tamper_evidence.json`.

## Phase 5 — enforcement plane / T5

- Structural check: static AST scan + dynamic `GuardedVerdictDict` run confirm
  none of the nine forbidden verdict fields ever reaches `enforcement/`'s
  decision path. `artifacts/phase5_structural_check.json`.
- Adversarial forcing: **0/12** envelope violations (target: 0) across every
  attack class including the four no-detector classes, verdict forced to
  Normal by direct kernel-key compromise (models A_data). Figure [T5]:
  `realise(Normal) = (1000, 500)` vs. intended `(1600, 800)` under Ceil =
  (1000, 500). `artifacts/phase5_figure_t5.json`,
  `artifacts/phase5_adversarial_forcing.json`.
- Slew containment: 0 violations across a forced Normal↔Safe oscillation.
  `artifacts/phase5_slew_containment.json`.

## Phase 6 — observer / actuation fidelity

- Structural independence: static+dynamic scan confirms
  `trust_kernel.schema.sign_statement`/`build_statement` are never called
  from `enforcement/`. `artifacts/phase6_structural_check.json`.

## Phase 7 — real BCI pipeline substrate

- 9-subject BCIC IV 2a, hash-pinned MOABB load, cross-session (train on T,
  eval on E). Decoding accuracy is explicitly not a result (§17a scope guard)
  — reported only as the substrate that produces real per-subject variability
  for later phases. `artifacts/phase7_per_subject_summary.json`.

## Phase 8 — evidence producers

- Six real producers wired to real trial data and the real T4→kernel→
  enforcement path, including one real firmware attack (FSI PCR mismatch,
  boot-time) and one real communication attack (Device invalid-cert DTLS
  handshake) on real subject-1 data. `artifacts/phase8_evidence_producers_report.json`.

## Phase 8.5 — SBA validation

- CTPR has zero effect on P(Verdict=Safe) under same-severity propagation,
  proven exact by exhaustive 729-combination enumeration for the deployed DAG
  (FSI→Signal, FSI→Model). `artifacts/phase8_5_sba_validation_report.json`,
  `docs/PHASE8.5-SBA-VALIDATION.md`.

## Phase 9 — measured ROC / thresholds

- Per-claim θ1/θ2/band_cap derived at all 3 swept budgets {0.1%, 1%, 5%} from
  real subject data. Model/Device/FSI: `stable` on the held-out {4–9} cohort
  (degenerate, perfectly-separated ROCs). Signal/Calibration: `tail_floor` at
  **all three** budgets on the full 9-subject pool (continuous ROCs, measured
  sub-resolution). `config/eis.v1-measured.json`,
  `artifacts/phase9_measured_roc_report.json`, `docs/PHASE9-MEASURED-ROC.md`.
- `calibration_status: provisional` (ActuationFidelity has no offline
  measurement path; `validate_eis_config()` correctly refuses `measured`).

## Phase 10 — latency evaluation

- Headline overhead (4-producer path, excl. FSI, N=200 real trials, subject
  1): **p50 = 5.82%, p99 = 8.86%** of the 100ms window.
- Kernel decision: p99 = 0.147ms (budget κ≤5ms — clears with 97% margin).
- **FSI included honestly** (N=30 real swtpm quotes): decision-path p99 =
  93.5ms (budget 67ms, **VIOLATED**, margin −26.5ms); admission p99 = 89.4ms
  (Δ(w)=60ms, **VIOLATED**, margin −29.4ms). Resolved as a performance/
  deployability question, not a security one, since T5 does not depend on any
  sensor's cadence — see `docs/PHASE10-LATENCY-EVALUATION.md` §4 and
  `docs/THREAT-MODEL.md` §4.
- Deadline invariant demonstrated empirically: a hung Signal producer (2.0s
  sleep, 33× the deadline) never delays the verdict — collection bounded at
  ~60ms (the deadline), not ~2000ms (the hang); hung dimension reads LOW via
  absence. `artifacts/phase10_latency_evaluation_report.json`.

## Phase 11 — behaviour-level attack framework

10 real attacks, real runtime-behaviour injection, real evidence path.
**6/10 detected**, **4/10 no-detector-by-design** (signal_injection,
adversarial_eeg — a genuine detector blind spot, not a threshold artifact;
model_poisoning; actuator_manipulation), **10/10 consequence-bounded**
regardless (T5, restated from Phase 5, never re-derived).
`artifacts/phase11_attack_framework_report.json`,
`provenance/phase11_attack_framework_manifest.json`.

## Phase 12 — fault injection / robustness

- 6/6 faults reach their specified fail-safe mode (kernel termination,
  enforcer termination, 6× producer suppression, verdict expiry, log
  corruption, log-path exhaustion) — with the explicit caveat that reaching a
  physically-Safe actuator state after a process death is watchdog/hardware
  territory (CLAUDE.md §6), not established by software alone.
- Honest-operation false-positive rate (846 real windows, subjects 1–3, real
  Signal/Calibration per trial): shipped measured config → **0% Safe, 99.4%
  Constrained, 0.6% Normal**. Swept-budget sensitivity (Phase 9's already-
  derived thresholds, re-cited not re-derived): 0.1%→0% Normal, 1%→0.6%
  Normal, 5%→4.5% Normal — monotone in the expected direction.
  `artifacts/phase12_fault_injection_report.json`.

## Mutation testing (all harnesses, fresh run)

| Harness | Result |
|---|---|
| `mutation_check.py` (pure core) | 61/61 |
| `mutation_check_eis_v1.py` | 11/11 |
| `mutation_check_event_model.py` | 12/12 |
| `mutation_check_sba.py` | 12/12 |
| `mutation_check_threshold_derivation.py` | 14/14 |
| `mutation_check_roc_estimability.py` | 13/13 |
| `mutation_check_latency.py` | 13/13 |
| `mutation_check_attack_coverage.py` | 10/10 |

**146/146 (100%)** across all 8 harnesses. `artifacts/mutation_summary.json`.

## Test suites

`tests/` 234, `tests_event_model/` 41, `tests_sba/` 20, `tests_roc_estimability/`
70, `tests_sensors/` 34, `tests_latency/` 23, `tests_attack_framework/` 12 —
**434 tests**, all passing.
