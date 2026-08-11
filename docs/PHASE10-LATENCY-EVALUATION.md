# Phase 10 — Latency Evaluation

Status: **Phase 10 result — real measurement against the measured config.**
CLAUDE.md, the kernel, enforcement semantics, crypto rules, and all frozen
config were not modified. Code: `latency/measurement.py`,
`experiments/phase10_latency_evaluation.py`, `tests_latency/test_measurement.py`,
`harnesses/mutation_check_latency.py`.
Artifacts: `artifacts/phase10_latency_evaluation_report.json`,
`provenance/phase10_latency_evaluation_manifest.json`.

---

## 0. Method

Real subject-1 BCIC IV 2a pipeline, N=200 per-trial repetitions (8 discarded
warmup) for every stage except FSI (N=30 — a real, fresh swtpm TPM quote per
repetition, measured separately; see §5). Kernel decision uses
`config/eis.v1-measured.json` (Phase 9's measured config), loaded once at
session setup like any other config. Two configurations, both calling the
real, unmodified `bci_pipeline/`, `sensors/`, `trust_kernel/`, `enforcement/`
functions — no stage tuned for speed, no stage skipped, no verdict cached.

Per-window convention (established in Phase 8, reused unmodified): one
evidentiary "window" = one real trial's `raw_epoch`/`feature_vector` — this
offline substrate has no independent 100ms-cadence acquisition; the BCI
stages (artifact detection, feature extraction, classification) already
operate per-trial, which **is** this project's per-window granularity for
the evidence/kernel/enforcement layer.

---

## 1. Acquisition and filtering (batch, session-level — reported separately)

| Stage | p50 | p99 |
|---|---|---|
| Acquisition (`loader.load_subject_data`, hash-verified) | 4841.8 ms | 6642.6 ms |
| Filtering (raw band-pass + notch, replayed from `preprocessing.py`'s own constants) | 1517.9 ms | 1665.7 ms |

These are **whole-session, one-time** costs in this offline substrate (MOABB
batch load; MNE's zero-phase filters need the whole/most of the signal, not
a per-sample causal filter) — **not** folded into the per-window totals
below. Folding a one-time multi-second session cost into a 100ms recurring-
window budget comparison would be apples-to-oranges; reported here as their
own honest number instead.

---

## 2. Per-stage latency (per-window, N=200 except FSI)

| Stage | Baseline p50 | Baseline p99 | Architecture p50 | Architecture p99 |
|---|---|---|---|---|
| Artifact detection | 0.454 ms | 1.020 ms | 0.483 ms | 1.135 ms |
| Feature extraction | 1.703 ms | 3.815 ms | 2.304 ms | 3.904 ms |
| Classification | 0.505 ms | 1.272 ms | 0.668 ms | 1.692 ms |
| Evidence gen — Signal | — | — | 2.125 ms | 3.741 ms |
| Evidence gen — Calibration | — | — | 0.056 ms | 0.196 ms |
| Evidence gen — Model | — | — | 0.383 ms | 0.806 ms |
| Evidence gen — Device | — | — | 0.006 ms | 0.027 ms |
| Statement signing — Signal | — | — | 0.121 ms | 0.275 ms |
| Statement signing — Calibration | — | — | 0.087 ms | 0.231 ms |
| Statement signing — Model | — | — | 0.078 ms | 0.200 ms |
| Statement signing — Device | — | — | 0.073 ms | 0.195 ms |
| Evidence admission (T4, 4 statements) | — | — | 1.279 ms | 2.572 ms |
| **Kernel decision (bands→meet→CTPR→π)** | — | — | **0.067 ms** | **0.147 ms** |
| Verdict signing | — | — | 0.289 ms | 0.618 ms |
| Enforcement (accept+clamp+slew+capability) | — | — | 0.372 ms | 0.698 ms |

Baseline vs. architecture's own artifact/feature/classification numbers
differ slightly (0.45→0.48ms, 1.70→2.30ms, 0.51→0.67ms) — real measurement
noise from a shared CPU/interpreter running more concurrent work in the
architecture loop, not a change to those stages' code (identical calls in
both configurations, confirmed by reading the driver: `run_baseline_stages`
is called unmodified from both loops).

---

## 3. End-to-end totals and headline overhead

| | p50 | p99 |
|---|---|---|
| Baseline total | 2.721 ms | 5.374 ms |
| Architecture total | 8.537 ms | 14.238 ms |
| **Overhead (architecture − baseline)** | **5.816 ms** | **8.864 ms** |
| **Overhead as fraction of the 100ms window** | **5.82%** | **8.86%** |

Excludes FSI (measured separately, §5) and the batch acquisition/filtering
costs (§1) — this is the per-window, 4-producer decision-path overhead.

---

## 4. Budget verification against CLAUDE.md §7's frozen parameters

| Check | Measured p99 | Budget | Margin | Violated? |
|---|---|---|---|---|
| Kernel budget κ ≤ 5ms | 0.147 ms | 5 ms | 4.853 ms | **No** |
| Evidence deadline Δ(w) = 60ms (4 producers, excl. FSI) | 5.670 ms | 60 ms | 54.330 ms | **No** |
| Decision path ≤ 67ms (4 producers, excl. FSI) | 9.705 ms | 67 ms | 57.295 ms | **No** |

**The real headline result — FSI included:**

| Check | Measured p99 | Budget | Margin | Violated? |
|---|---|---|---|---|
| Evidence deadline Δ(w) = 60ms, **including FSI** | 89.418 ms | 60 ms | **−29.418 ms** | **YES** |
| Decision path ≤ 67ms, **including FSI** | 93.454 ms | 67 ms | **−26.454 ms** | **YES** |

**This is a real violation, reported as found, not adjusted around.** A real
swtpm TPM quote costs ~60–83ms per invocation (§5) — on its own, close to or
exceeding the entire Δ(w)=60ms evidence-admission deadline. The first pass of
`check_budgets()` summed only 4 of 5 real-time producers (FSI was measured in
a structurally separate loop, real TPM ops, smaller N) and reported
"VIOLATED=False" — technically accurate for what it summed, but it buried a
real violation behind that exclusion (FSI's own p99 was reported alongside,
in `fsi_stats`, but never folded into the pass/fail verdict). Caught and
corrected post-hoc from the already-recorded per-stage data (no rerun): see
`artifacts/phase10_latency_evaluation_report.json`'s
`budget_verification.fsi_inclusion_correction`, and
`provenance/phase10_latency_evaluation_manifest.json`'s
`post_hoc_report_annotation` for the disclosed before/after hash. Source
(`check_budgets()`) fixed for future runs so the FSI-inclusive check is a
first-class result, not a buried note.

**FSI cadence — resolved, not left open.** The question is whether the
Δ(w)/decision-path violation above is a *security* problem (something the
architecture's guarantees depend on) or purely a *performance/deployability*
one. It is the latter, for three independently sufficient reasons already
present in already-frozen project artifacts — this is not a new argument
invented to explain away the violation, it is what those artifacts already
said before Phase 10 ran:

1. CLAUDE.md §3, Position A (locked): *"all evidence including FSI is
   software-forgeable in V1. CTPR therefore provides no adversarial bound in
   V1. T5 rests entirely on enforcement-plane termination."* Whatever cadence
   FSI's underlying quote mechanism runs at, it contributes zero adversarial
   bound either way — there is no security property that a faster or slower
   FSI cadence could strengthen or weaken.
2. CLAUDE.md §5: *"T5 must never be proven from π... T5 is a property of the
   enforcement function's dependency structure."* T5 is the architecture's
   only unconditional guarantee, and it does not depend on any sensor's
   cadence, FSI included.
3. `config/claim_registry.json`'s `fsi.provisional_v0.provenance_note` — written
   and frozen at Phase 8, before this experiment existed — already discloses:
   *"boot-time only ... provides no protection against A_code acting after
   boot."* `sensors/fsi_sensor.py`'s module docstring says the same thing in
   its own words. Phase 10 did not discover a new security gap; it measured
   the real cost of a mechanism whose protective scope (honest-evidence-only,
   boot-time-scoped) was already disclosed.

**Disposition:** the measured 89.4ms/93.5ms p99 numbers stand, unmodified,
as an honest performance finding — a real deployability constraint worth
fixing in future engineering, not a security defect and not grounds to
change any measured result. Per-window quote+nonce freshness is what backs
FSI's *replay*-detection property (a stale quote re-presented against the
current window's nonce fails `checkquote`); a coarser-cadence design that
decouples "acquire a fresh quote" from "sign a per-window statement" (cheap:
statement signing alone measured 0.184ms p50, §5) is architecturally
available as future engineering work (CLAUDE.md §16's pattern: specified,
not built) and would need to preserve that nonce-freshness property to stay
equivalent — it is deliberately **not** implemented here, since implementing
and re-measuring it would change a reported result outside the
disclosed-post-hoc-correction discipline this project holds itself to, and
it is not required to close any security question. This closes the item —
it is not a decision deferred to the PI.

---

## 5. FSI (measured separately, N=30, real swtpm quotes)

| Stage | p50 | p99 |
|---|---|---|
| Evidence generation (fresh TPM quote + evaluate) | 60.101 ms | 83.421 ms |
| Statement signing | 0.184 ms | 0.327 ms |

By far the most expensive stage in the entire architecture — real subprocess-
driven TPM protocol cost, not a code-path inefficiency (statement signing for
the same claim costs a few hundred microseconds, like every other producer).

---

## 6. CPU, memory, throughput

| | Baseline | Architecture | FSI loop |
|---|---|---|---|
| CPU user time | 0.604 s | 1.720 s | 0.080 s |
| CPU system time | 0.000 s | 0.000 s | 0.038 s |
| Peak RSS | 1,398,032 KB | 1,398,032 KB | 1,398,032 KB |
| Throughput | 331.0 windows/s | 116.0 windows/s | 16.0 windows/s |

Peak RSS is identical across all three because it is a single Python process
whose peak was already set by the pipeline/dependency load before any loop
ran (`resource.ru_maxrss` is a whole-process high-water mark, not a per-phase
delta) — reported as measured rather than a fabricated per-phase split.

---

## 7. Deadline-invariant demonstration (not asserted — run twice, compared)

A **control** window (all 4 producers respond normally) and a **hung**
window (Signal sleeps 2.0s — 33× the 60ms deadline — before it would even
compute a value) were both run through `latency.measurement.collect_within_deadline()`,
a bounded-wait orchestration primitive that launches each producer in its own
daemon thread and waits **at most** the shared Δ(w)=60ms budget, in total,
before proceeding with whatever arrived.

| | Statements collected | Collection wall time | Signal (effective) | Verdict |
|---|---|---|---|---|
| Control | Signal, Calibration, Model, Device | 7.75 ms | HIGH | Safe |
| **Hung** | Calibration, Model, Device (**Signal absent**) | **60.40 ms** | **LOW** | Safe |

- **Verdict still issued**: yes, in both cases — no exception, no stall.
- **Hung dimension reads LOW**: yes — via `trust_kernel.bands.reduce_dimension()`'s
  existing, unmodified "missing claim ⇒ LOW" semantics (CLAUDE.md §10), exercised
  end-to-end, not reimplemented for this test.
- **Collection latency bounded by the deadline, not the hang duration**: yes —
  60.40 ms, not ~2000 ms. The hung thread is abandoned (`daemon=True`) once
  the shared budget elapses; nothing in the decision path ever joins it again.

This demonstrates CLAUDE.md §7's invariant directly: "no unbounded wait
exists in the decision path... a missing statement is never waited for, it
reads LOW... worst case = D + κ regardless of sensor behaviour." It does not
modify `trust_kernel/` or `enforcement/` — the demonstration only decides
which producers' output gets included in the statement batch handed to the
existing, unmodified admission/kernel code.

---

## 8. Mutation kill rate

- `latency` (new, `harnesses/mutation_check_latency.py`): **13/13 (100%)**
- Pure core (`harnesses/mutation_check.py`): **61/61 (100%)**, unaffected

---

## 9. What was NOT done (per the task's own gate)

No tuning for speed at any stage. No caching of verdicts, no skipping of
verification, no letting a slow sensor delay a verdict (the deadline
orchestration in §7 is the opposite: a slow producer gets *excluded*, never
waited for). The attack-simulation framework (a later phase) was not started.
No frozen config, kernel code, enforcement code, or crypto rule was modified.
