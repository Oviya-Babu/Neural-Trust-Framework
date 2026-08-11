# Limitations

Status: **consolidated, stated plainly.** This document exists so that no
limitation is scattered, softened, or discoverable only by reading between
the lines of a phase report. Each item below is already established
elsewhere in this repository; nothing here is new. Cross-referenced, not
duplicated in substance.

## 1. The version-control freeze is not an external pre-registration

CLAUDE.md's freeze (git history, hash records like the SBA-freeze commit) is
a discipline this project holds itself to, not an independently-verifiable
commitment. A git timestamp is rewritable and reviewers know it (CLAUDE.md
§13). The actual pre-registration vehicle is `docs/OSF-PREREGISTRATION.md` —
**drafted, not submitted.** Until it is submitted to an external registry,
every "frozen before this ran" claim in this repository is self-attested,
not independently timestamped.

## 2. Signal and Calibration are tail-floored at all three swept budgets

Per `docs/PHASE9-MEASURED-ROC.md` and `docs/ROC-ESTIMABILITY-DIAGNOSTIC.md`:
these two claims' thresholds are not point estimates at *any* of the three
illustrative budgets {0.1%, 1%, 5%} — every one is a conservative floor
("no tighter than X"), set by the Tail-Floor Rule because the operating point
is not stably resolvable from available data (class support, bootstrap
band-width, or leave-one-subject-out swing fails the fixed bars). This is not
a per-budget issue that resolves at a looser budget — it is measured to hold
at all three. Model, Device, and FSI do not share this limitation (`stable`
on the held-out cohort), but their absence of failure reflects degenerate,
perfectly-separated ROCs and protocol-level subject-invariance, not a
stronger real-world detection capability.

## 3. ActuationFidelity has no offline measurement path

No offline per-subject data exists for it under honest, no-live-enforcement-
loop operation (`docs/ROC-ESTIMABILITY-DIAGNOSTIC.md`'s per-claim disclosure
table). `resolution_status` is `pending` at every budget, and
`trust_kernel.bands.validate_eis_config()` will refuse `calibration_status:
measured` while this remains a placeholder — enforced in code, not merely
documented (`config/eis.v1-measured.json`'s ActuationFidelity claim carries
`placeholder: true`).

## 4. FSI and Device are ungrounded on this hardware class

Per `config/claim_registry.json`'s provenance fields, restated in
`docs/THREAT-MODEL.md` §4:

- **FSI**: `EMULATED_PROTOCOL`, boot-time only. The PCR-extend happens once
  at simulated boot; every subsequent quote attests to that one boot-time
  measurement, not to ongoing runtime execution. An attacker with code
  execution after boot (A_code) is invisible to FSI by construction.
- **Device**: `EMULATED_PROTOCOL`, off-path. The real DTLS handshake this
  producer drives is a standalone protocol exercise — the actual EEG data
  path does not traverse it in this software-only prototype.

Neither claim discharges TA1's writability clause against A_code (§3) — only
a hardware root of trust does that, and none exists in V1 (§16, future work).

## 5. The offline-evaluation boundary

Two structurally different claim families, evaluated differently:

- **Emulated-protocol claims** (Model, Device, FSI): resolve cleanly.
  Integrity checks (hash+signature, DTLS handshake, PCR/quote) are boolean-
  like and produce degenerate, perfectly-separable ROCs — real cryptography
  and real protocol state machines, evaluated correctly on this substrate.
- **Measured-EEG claims** (Signal, Calibration): cannot be sharply calibrated
  on trial-structured offline data. BCIC IV 2a provides discrete trials, not
  the continuous stream a deployed system would see; combined with a
  9-subject cohort, this is exactly why §2 above holds and is not a defect
  in the derivation, it is the honest resolution limit of this dataset.

## 6. FSI's per-window attestation cost

Measured (`docs/PHASE10-LATENCY-EVALUATION.md` §4): a real swtpm quote costs
~60–83ms per invocation, which — included honestly in the per-window
decision path — violates both the 60ms admission deadline and the 67ms
decision-path budget. **This question is resolved, not open**: under
Position A (§3) and T5's independence from π (§5), no sensor's cadence
affects any security guarantee, so this is a performance/deployability
finding, not a security gap. A coarser-cadence design (decoupling quote
acquisition from per-window statement signing) is documented as available
future engineering work but was deliberately not implemented, since doing so
would have required re-measuring an already-reported result outside this
project's disclosed-post-hoc-correction discipline.

## 7. Software-only

No hardware root of trust in V1 (§16 specifies what would be needed: ATECC608B
attestation, an in-path hardware ceiling MCU — neither is built). No live BCI
hardware, no live human subjects, no clinical deployment (§1). No clinical
population — BCIC IV 2a is nine healthy adults (§17a's scope guard); this
project supports no clinical-relevance claim and targets a CPS/security
venue, not a clinical journal.

## What these limitations do not undermine

T5 (consequence-boundedness) does not depend on any of the above — it is a
property of `enforcement/clamp.py`'s dependency structure (Ceil is a
load-time constant, never a function of ν), verified independently of
detector quality, calibration status, or hardware grounding. Every limitation
above concerns the *honest-evidence* half of this architecture's claims
(detection, CTPR propagation, T4 freshness), which this project has never
claimed to hold against A_code — see `docs/THREAT-MODEL.md` §3's honest
partition table.
