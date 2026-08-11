# Phase 8.5 — SBA (Session Budget Allocation) Validation

Status: **validation report for PI review — CLAUDE.md not modified by this pass.**
Code: `sba_validation/`, `tests_sba/`, `harnesses/mutation_check_sba.py`,
`experiments/phase8_5_sba_validation.py`.
Artifacts: `artifacts/phase8_5_sba_validation_report.json`,
`provenance/phase8_5_sba_validation_manifest.json`.

---

## 0. The question

A flat per-claim α allocation spreads a session-level spurious-restriction
budget evenly across claims and windows, computed as if each claim's
false-alarm event were independent. CTPR (`effective_child = meet(child,
g(FSI_level))`, `g = identity`, edges `FSI→Signal`, `FSI→Model`)
intentionally introduces a dependency between FSI and two other claims.
**Does that dependency invalidate the flat allocation's session-level
guarantee?**

---

## 1. Formal probability model

### 1.1 Setup

At window *w*, claim *d*'s **raw** trust level `L_d(w) ∈ {LOW, MED, HIGH}`
is a random variable under honest (non-adversarial) operation, with

```
P(L_d = LOW)  = α_d                  (FPR at θ1, by construction: CLAUDE.md §4)
P(L_d = MED)  = α2_d − α_d           (α2_d := FPR at θ2 ≥ α_d)
P(L_d = HIGH) = 1 − α2_d
```

`band_cap = HIGH` is assumed throughout (a detector that actually attains
TPR ≥ 1−β); the weak-detector `band_cap = MED` case is an orthogonal,
already-covered concern (`tests/test_bands.py`'s `DeriveThresholdsTests`),
not remodelled here. The **six raw claims are modelled as mutually
independent** — a distinct measurement channel per dimension under honest
operation. This is the one place true "claim independence" is assumed, and
it is *not* the assumption CTPR threatens (see §1.4).

CTPR gives `effective_child = meet(child, g(parent))`, `g = identity`, so
for the deployed DAG:

```
Eff_Signal = min(L_Signal, L_FSI)
Eff_Model  = min(L_Model,  L_FSI)
Eff_d      = L_d      for d ∈ {Calibration, Device, FSI, ActuationFidelity}
```

Policy (`trust_kernel/policy.py`, unmodified, read directly):

```
crit_strict(LOW)=Safe,  crit_strict(MED)=Constrained,  crit_strict(HIGH)=Normal
crit_lenient(LOW)=Constrained, crit_lenient(MED)=Constrained, crit_lenient(HIGH)=Normal
Verdict = min_d crit_d(Eff_d)
```

Strict = {Signal, Model, Calibration, FSI, ActuationFidelity}. Lenient = {Device}.

### 1.2 The two target quantities

- **P(Verdict = Safe)** — full halt.
- **P(Verdict < Normal)** — any restriction (Constrained-or-worse).

### 1.3 Central result — proved, not estimated

**Claim.** For the deployed DAG, CTPR has *zero* effect on either target
quantity: the flat/naive formula (ignoring CTPR entirely) is **exact**,
not merely a bound or a negligible approximation.

**Proof sketch (full proof in `sba_validation/probability_model.py`
docstrings; machine-checked in `tests_sba/`):**

`Eff_Signal < HIGH ⟺ L_Signal < HIGH ∨ L_FSI < HIGH`, and symmetrically for
Model. So:

```
Verdict < Normal ⟺ ∃d: Eff_d < HIGH
                  ⟺ (L_Signal<HIGH ∨ L_FSI<HIGH) ∨ (L_Model<HIGH ∨ L_FSI<HIGH) ∨ L_Calib<HIGH ∨ L_Device<HIGH ∨ L_FSI<HIGH ∨ L_AF<HIGH
                  ⟺ L_Signal<HIGH ∨ L_Model<HIGH ∨ L_Calib<HIGH ∨ L_Device<HIGH ∨ L_FSI<HIGH ∨ L_AF<HIGH   (∨ is idempotent)
```

The `L_FSI<HIGH` term added by each CTPR edge is **already** a member of
the union via FSI's own raw term — CTPR adds no new root cause, because
its only parent (FSI) is already one of the six unioned dimensions. This
argument uses no strict/lenient distinction at all, so **P(Verdict<Normal)
is unaffected by CTPR unconditionally, for *any* DAG shape**, as long as
every parent is a monitored dimension (true here, and true of any DAG
built from `config/claim_registry.json`'s dimensions).

For `Verdict = Safe` specifically, the same idempotence argument holds
*conditional on same-severity propagation*: because `crit_strict` is a
strictly monotonic bijection `LOW↔Safe, MED↔Constrained, HIGH↔Normal`, it
commutes with `meet`: `crit_strict(min(a,b)) = min(crit_strict(a),
crit_strict(b))`. Composing this with `min(a, min(b,a)) = min(a,b)` gives,
for the FSI→Signal edge alone:

```
π_{Signal,FSI} = min(crit_strict(Eff_FSI), crit_strict(Eff_Signal))
              = min(crit_strict(L_FSI), min(crit_strict(L_Signal), crit_strict(L_FSI)))
              = min(crit_strict(L_Signal), crit_strict(L_FSI))
```

— **exactly** what a no-CTPR calculation would give. This holds because
FSI (the parent) and Signal, Model (the children) all use the **same**
`crit_strict` table.

**Machine verification:** `tests_sba/test_probability_model.py`'s
`RealDagIdempotenceTests` exhaustively enumerates all 3⁶ = 729 raw-level
combinations through the real, unmodified `trust_kernel.ctpr.apply_ctpr`
and `trust_kernel.policy.policy` (cross-checked bit-for-bit against a
generic reimplementation in `GenericImplementationMatchesRealHardcodedFunctionsTests`),
at a small-α regime, a tiny/realistic-α regime, and a **stress regime
where α_FSI is 300× the other claims' α** — confirming the result is
exact, not a small-α asymptotic artifact.

### 1.4 Where the concern *is* valid

The independence assumption **does** break — just not for the quantity
SBA cares about. CTPR genuinely inflates Signal's and Model's *marginal*
(per-dimension) observed false-alarm rate from `α_d` to `α_d + α_FSI ·
(1−α_d)` ≈ `α_d + α_FSI`. This matters for:

- **Phase 9 measured-ROC attribution**: if Signal's field-observed LOW
  rate is compared against its *own* configured α without accounting for
  FSI's contribution, it will look like Signal's detector under-performs
  its ROC when the excess is actually FSI-attributable.
- **Per-dimension SLA/diagnostic reporting**, if ever wanted.

It does **not** matter for the session-level restriction-probability
budget, because that budget is a question about the *union* of triggering
events, and the union is provably unaffected (§1.3).

### 1.5 Precise boundary — when the concern *would* become material

The same-severity requirement in §1.3's second half is load-bearing. A
**hypothetical** edge from a **lenient** parent `P` into a **strict**
child `C` breaks it: `P`'s own ordinary failure (`crit_lenient(LOW) =
Constrained`) gets **severity-escalated** to `Safe` via `C`'s
`crit_strict` table, because `Eff_C = meet(C, P) = LOW` whenever `P =
LOW`, regardless of `C`'s own raw level. This is a genuinely **new**
causal path to `Safe` that did not exist before the edge, worth
`≈ α_P` of session-budget the naive formula would miss entirely.
Quantified and validated empirically in §3.4.

**Conclusion for Step 1: the concern is mathematically valid in general,
but for the specific two-edge DAG currently in `config/ctpr.json`
(FSI[strict]→Signal[strict], FSI[strict]→Model[strict]), the naive/flat
formulation is exact — not "negligible," zero.** The correction that
*would* be needed is precisely characterized (§1.5, §2) but not currently
applicable.

---

## 2. Derivation (forward-looking — not applied to the deployed DAG)

Per §1's conclusion, **no correction is required for the system as
specified today.** The following is derived so that if the DAG grows to
include a cross-severity edge, the correct methodology is already on
record (CLAUDE.md §18: redesign only on demonstrated necessity — this is
that necessity, pre-derived, not yet triggered).

**General principle — apportion across the ancestor closure of the strict
set, not just the strict set itself:**

```
P(Verdict = Safe) = 1 − Π_{d ∈ Ancestors(strict)} (1 − α_d)

where Ancestors(strict) = strict ∪ { every CTPR ancestor of every d ∈ strict }
```

**Why the old formulation fails:** it apportions budget only across
`strict`, silently omitting any non-strict ancestor that can drag a
strict dimension to LOW through `meet`.

**Why the new formulation is correct:** `Eff_d = LOW` for `d ∈ strict` iff
`raw_d = LOW ∨ (∃ ancestor a of d: L_a = LOW)` (meet/idempotence, same
argument as §1.3, generalized). The Safe-triggering event is therefore
exactly the union over `Ancestors(strict)`'s raw-LOW events; independence
across that (now possibly-larger) set gives the product-complement form
above by the standard inclusion-exclusion argument for independent events.

**Assumptions** (stated explicitly, each separable from the others):

1. Raw per-claim events are mutually independent within a window (§1.1) —
   a genuine modelling choice about distinct measurement channels, not
   examined further here.
2. **Windows are independent and identically distributed across time**
   (used to convert a per-window probability to a session probability via
   `1−(1−p)^W`). This is a **separate approximation from the CTPR
   question** — EEG/sensor noise plausibly has short-range temporal
   correlation that this treats as absent. It is the standard
   reliability-engineering simplification, not examined further here, and
   is explicitly NOT the same concern as §1's CTPR-dependence question.
3. `band_cap = HIGH` (§1.1) throughout.

**Limitations — what breaks the derivation if the DAG grows:**

- Any edge whose parent is not already in the same severity class
  (strict/lenient) as a strict descendant requires re-deriving
  `Ancestors(strict)` (mechanical, but must be re-run).
- Multiple parents into one child, or multi-hop chains, still reduce to
  the same ancestor-closure union (meet is associative/idempotent), but
  the *independence* assumption underlying the product form gets weaker
  as the ancestor set grows and shares more structure — worth revisiting
  empirically, not just formally, if the DAG becomes dense.
- This entire analysis assumes exactly one claim per dimension (matching
  the current `config/claim_registry.json` 1:1 mapping). Multiple claims
  per dimension reduce via `meet` too (`reduce_dimension`), and the same
  idempotence machinery applies, but was not separately re-verified here.

---

## 3. Empirical validation

Nominal validation input: **B = 1% per 8h session** (288,000 windows at
10 Hz, CLAUDE.md §7) — a test fixture only, not a deployment
recommendation (per the task's explicit instruction).

### 3.1 Real DAG at the nominal budget

| Quantity | Value |
|---|---|
| Target session budget B | 1.0000% |
| Required α per strict claim (flat split, 5 claims) | 6.979 × 10⁻⁹ |
| α in basis points | 0.00007 bp (< 1 bp — **not representable**, see §3.3) |
| Exact `p_window(Safe)`, CTPR **on** | 3.489700 × 10⁻⁸ |
| Exact `p_window(Safe)`, CTPR **off** | 3.489700 × 10⁻⁸ (bit-identical) |
| Naive formula `p_window(Safe)` | 3.489700 × 10⁻⁸ (bit-identical) |
| Session P(Safe), exact | 1.0000% |
| Session P(Safe), naive | 1.0000% |
| **Budget held?** | **Yes — exactly, by construction, since naive = exact** |

CTPR on vs. off and naive vs. exact all agree to floating-point precision
(< 1e-15) — this is §1.3's proof, confirmed numerically.

### 3.2 Naive vs. derived, side by side

For the **deployed DAG**, "derived" (§2's ancestor-closure formula)
degenerates to "naive" exactly, because `Ancestors(strict) = strict` (FSI
is already strict). There is nothing to contrast for this DAG — which is
itself the finding. The naive-fails/derived-passes contrast the task
requires is demonstrated instead on the **boundary case** (§3.4), where
the two formulations genuinely diverge.

### 3.3 Basis-point wire-format finding (orthogonal to CTPR)

A byproduct of computing §3.1's numbers: the required α (~7×10⁻⁹) is
**five orders of magnitude below** the smallest nonzero rate the current
wire format can express (`CLAUDE.md §8`: rates are basis points, 0..10000
→ minimum nonzero rate = 1×10⁻⁴). Using the *smallest representable*
nonzero α (0.0001) for all five strict claims instead:

| Quantity | Value |
|---|---|
| Min representable α (1 bp) | 1 × 10⁻⁴ |
| Resulting `p_window(Safe)` | ≈ 5 × 10⁻⁴ |
| Resulting **session** P(Safe) | **≈ 1.000000** (essentially certain) |

**This is a real, severe, and entirely separate finding from the CTPR
question**: at current basis-point granularity, *no* claim can be
configured tight enough to hold *any* of the swept session budgets
(§4) — the system would restrict almost every session, regardless of
CTPR. This touches CLAUDE.md §8 (FROZEN wire schema) and is **explicitly
out of scope for this pass** — flagged for separate PI escalation
(CLAUDE.md §18), not silently worked around.

### 3.4 Monte Carlo injection cross-check (real code path)

At a **representable, inflated** α (0.01 / 0.03 — chosen only so sampling
noise is small relative to effect size; not a target value), N = 20,000
windows, using **real** `trust_kernel.schema.build_statement` /
`sign_statement` / `verify_statement_signature`, `trust_kernel.bands.score`
/ `band` / `reduce_dimension`, `trust_kernel.ctpr.apply_ctpr`, and
`trust_kernel.policy.policy` — not a reimplementation:

| | Predicted (exact enumeration) | Measured (Monte Carlo, N=20,000) | Relative error |
|---|---|---|---|
| P(Safe) | 0.04901 | 0.04805 | 1.96% |
| P(<Normal) | 0.16703 | 0.16300 | 2.41% |

Both within expected binomial sampling noise (≈ 3% relative at this N and
p) — the real code path reproduces the theoretical prediction.

### 3.5 Boundary case: naive fails, corrected passes

Hypothetical (**not deployed**) lenient-parent(P)→strict-child(C) edge,
α_P=0.10, α_C=0.02:

| Formula | P(Safe) | vs. exact |
|---|---|---|
| Exact enumeration | 0.1180 | — |
| **Naive** (only strict dims counted) | 0.0200 | **underestimates by 0.0980 (83%)** |
| **Corrected** (ancestor closure, §2) | 0.1180 | matches exactly (< 10⁻¹²) |

This is the required naive-fails/derived-passes contrast — demonstrated
on the scenario where it actually applies, not manufactured on the
deployed DAG where it does not.

### 3.6 Mutation kill rate

- `sba_validation/` (new code, `harnesses/mutation_check_sba.py`):
  **12/12 (100%)**.
- Pure-core suite (`harnesses/mutation_check.py`), confirmed **unaffected**
  by this pass: **61/61 (100%)**.

---

## 4. Illustrative budget sweep

Research parameters only — same status as `Ceil`'s reference values
(§17/§6), not deployment recommendations.

| Session budget B | α per strict claim | α (bp) | Representable at 1bp? | Implied spurious halts/min at target | naive = exact? |
|---|---|---|---|---|---|
| 0.1% | 6.948 × 10⁻¹⁰ | 0.00001 | No | 2.084 × 10⁻⁶ | Yes |
| 1% | 6.979 × 10⁻⁹ | 0.00007 | No | 2.094 × 10⁻⁵ | Yes |
| 5% | 3.562 × 10⁻⁸ | 0.00036 | No | 1.069 × 10⁻⁴ | Yes |

The naive/flat formula matches the exact CTPR-aware computation at every
swept budget. None of the three illustrative budgets are representable at
the system's current 1-basis-point rate granularity (§3.3) — this holds
uniformly across the sweep, not just at the nominal 1% point.

---

## 5. Plain-language summary

**The original concern was mathematically reasonable to raise, but it does
not apply to the system as built.** CTPR's dependency structure (FSI
dragging down Signal and Model) turns out to add *zero* extra risk to the
session-level spurious-restriction budget, for a precise, provable reason:
FSI is already one of the dimensions being watched on its own, so nothing
new is added when it also drags its children down — the flat, per-claim
budget-splitting approach already in mind for Phase 9 is exactly correct,
not merely close enough. This was checked two ways — an exhaustive,
code-driven enumeration of every possible outcome, and a live simulation
that actually built and signed thousands of evidence statements and ran
them through the real trust engine — and both agree. **No fix is needed,
and none was applied.** The exercise did surface one real, unrelated
problem worth flagging separately: the system's current numeric format for
expressing false-alarm rates is too coarse to actually hit any of the
session-availability targets tested (even a very loose one), which is a
wire-format question, not a CTPR question, and is left for separate
review. We also derived — but did not need to use — the correct
math for a possible *future* case where a lower-severity sensor feeds
into a higher-severity one; if that's ever added, this document already
has the fix ready.

---

## 6. Proposed CLAUDE.md diff — for review only, NOT applied

No SBA section currently exists in CLAUDE.md; nothing above required
changing any FROZEN section (§3, §4, §6, §9 untouched). The only proposed
change is the pre-registered scope-clarification sentence, for §20/§28 —
**neither section exists yet either**; this diff assumes they will be
created when/if SBA methodology is formally adopted into the spec, and is
presented as prose to insert at that time, not as a line-numbered patch
against current content:

> *Add to §20/§28 (or wherever the eventual SBA methodology section
> lands):*
>
> "The session-availability budget governing α is an illustrative research
> parameter rather than a deployment requirement. In the absence of a
> target clinical deployment, illustrative budget values are evaluated
> parametrically in the same manner as the reference Ceil values. The
> methodology — not a particular budget value — is pre-registered."

**This diff is not applied.** CLAUDE.md is unchanged by this pass, per the
explicit gate on this task.
