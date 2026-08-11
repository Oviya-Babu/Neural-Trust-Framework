# EIS v1 — Evidence Interpretation Layer

Status: **consolidated reference.** Named in CLAUDE.md §11's required `docs/`
layout; did not exist as a standalone document before this pass (Phase A
audit finding, documentation drift, category ii — fixed here). Every claim
below is already established and frozen elsewhere (CLAUDE.md §4/§8/§13/§20,
`trust_kernel/bands.py`, `docs/PHASE9-MEASURED-ROC.md`,
`docs/EVENT-MODEL-INVESTIGATION.md`); this document adds no new claim, it
consolidates them into one place.

## 1. What EIS is

The Evidence Interpretation Stage (EIS) turns one sensor's `raw_measurement`
into a `TrustLevel ∈ {LOW, MED, HIGH}` for that claim, kernel-side, before
intra-dimension reduction (meet) and CTPR propagation. It is the "bands"
stage of `bands → reduce → CTPR → π` (`trust_kernel/bands.py`).

```
s = pol × raw_measurement                (lower = more attack-like, uniformly)
θ1 = max{t : FPR(t) ≤ α}                 (LOW boundary)
θ2 = min{t : TPR(t) ≥ 1−β}               (HIGH boundary)
band(s) = LOW if s<θ1; MED if s<θ2; else HIGH,  then ⊓ band_cap
```

`α` and `β` are the only hand-set values anywhere in interpretation (CLAUDE.md
§4). Every per-claim threshold is *derived* from measured ROC via
`derive_thresholds()` — never hand-assigned (CLAUDE.md §11, §15).

## 2. Two formats, one formula: eis.v0 → eis.v1

| | `config/eis.v0.json` | `config/eis.v1.json` / `eis.v1-measured.json` |
|---|---|---|
| Scale | basis points, 1e4 | parts-per-billion, 1e9 |
| Marker | no `eis_schema_version` field, `alpha_bp` present | `eis_schema_version: 1`, `alpha_ppb` present |
| `resolution_status` | absent (not a v0 concept) | required per claim, keyed by swept budget |

This is a **representation-only** change (CLAUDE.md §20): `score()`,
`band()`, `reduce_dimension()`, and `derive_thresholds()`'s formula are scale-
parametric and byte-identical in effect across both formats —
`trust_kernel/bands.detect_rate_format()` fail-closed-detects which format a
config uses from its own fields and rejects any config declaring both or
neither. `eis.v0.json` is never edited in place; `eis.v1` widened precision
because the SBA event-model's derived per-claim α (as low as 1.30e-7) is
unrepresentable in basis points (min nonzero rate 1e-4) — see
`docs/EVENT-MODEL-INVESTIGATION.md` §4.

## 3. `resolution_status` — estimation vs. representation

Two different limits, kept structurally separate (CLAUDE.md §20):

- **Representation** (this document, §2): can a rate be *expressed* at all in
  the config's fixed-point scale.
- **Estimability** (`docs/ROC-ESTIMABILITY-DIAGNOSTIC.md`): can a threshold be
  *stably located* from the data available, independent of whether it can be
  written down.

`resolution_status ∈ {pending, stable, tail_floor}` per claim per swept
budget records the second. It is a config-side field, covered by
`roc_config_hash` (one of §8's six signed config hashes) — **not** a
wire/signed field on any Statement or Verdict; nothing in T4 admission or
verdict issuance reads it (verified by `trust_kernel/schema.py` containing no
reference to it, and by mutation testing on `_validate_resolution_status`).
Editing it changes `roc_config_hash` exactly as editing a threshold would —
it is not silently editable, it is simply not part of the enforcement-path
five fields (§ENFORCEMENT-v1.md §2).

**Tail-Floor Rule** (CLAUDE.md §20, full text there): when a threshold's
operating point is not stably resolvable by the fixed bars (support, bootstrap
band-width, leave-one-subject-out swing), it is set to the tightest
empirically-resolvable point and labelled `tail_floor` — never extrapolated
into unmeasured tail, never presented as a point estimate.

## 4. Measured state (Phase 9)

Per `docs/PHASE9-MEASURED-ROC.md` and `config/eis.v1-measured.json`:
`calibration_status: provisional` (ActuationFidelity has no offline
measurement path; the validator correctly refuses `measured`). Per-claim
`resolution_status` at all three swept budgets {0.1%, 1%, 5%}:

| Claim | Cohort | Status |
|---|---|---|
| Model, Device, FSI | held-out {4–9} | `stable` (degenerate/two-cluster ROC — see §5) |
| Signal, Calibration | full 9-subject pool | `tail_floor` (continuous ROC, sub-resolution α/β genuinely binds) |
| ActuationFidelity | — | `pending` (no offline measurement path) |

## 5. Degenerate vs. continuous ROC (the sub-ppb disposition)

Model/Device/FSI have perfectly-separated, two-cluster ROCs: `θ1 = θ2` at the
tightest observed point, invariant to `alpha_ppb` across the full swept range
(verified directly against `derive_thresholds()`, `docs/PHASE9-MEASURED-ROC.md`
§5) — the operating point is fixed by the class gap, not by locating a rate
on a continuous curve, so a sub-ppb nominal α simply never binds. Signal/
Calibration have continuous, ~100+-point ROCs where a sub-resolution α *does*
select a specific, unstable data point — exactly where the Tail-Floor Rule
fires. Same formula in both cases; no special-casing.

## 6. What EIS is not

Not a runtime component — it runs entirely kernel-side, in π's pure call
path (no I/O, no state, no clocks, no floats — CLAUDE.md §11). Not a
confidence computation — sensors never compute confidence (§2); ROC-derived
quantities live only in this interpretation layer. Not adversarially sound —
under Position A (`docs/THREAT-MODEL.md` §2) every `raw_measurement` feeding
EIS is honest-evidence-conditional; EIS never contributes to T5.
