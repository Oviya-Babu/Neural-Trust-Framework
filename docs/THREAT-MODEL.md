# Threat Model (FROZEN)

Status: **consolidated reference.** Named in CLAUDE.md §11's required `docs/`
layout; did not exist as a standalone document before this pass (Phase A
audit finding, documentation drift, category ii — fixed here). This is
CLAUDE.md §3 restated in one place with its consequences traced through the
rest of the architecture; it introduces no new claim, and it is frozen —
changes require PI escalation per CLAUDE.md §18.

## 1. Two adversaries — do not collapse them

**A_data** — forges any evidence statement, any signature, any verdict;
compromises any sensor and the Trust Kernel; controls all host clocks; reads
all host memory. Does **not** execute code inside the enforcement process.

**A_code** — arbitrary code execution at host privilege, including inside
the enforcer.

The distinction is load-bearing: A_data explains why T4 (verdict
authenticity + freshness) is honest-evidence-conditional rather than
adversarially sound. A_code explains why T5 cannot rest on anything
software-side at all — it is why the enforcement bound depends on Ceil being
*hardware*-provisioned in any deployment that needs to hold against A_code
(§16, not yet built in V1).

## 2. Position A (locked)

> All evidence including FSI is software-forgeable in V1. CTPR therefore
> provides no adversarial bound in V1. T5 rests entirely on
> enforcement-plane termination.

TA1 (Ceil is not adversary-writable) splits by adversary:

| Clause | Holds against | Discharged by |
|---|---|---|
| Ceil is not a function of ν | A_data and A_code | Dependency analysis (`enforcement/clamp.py`, ENFORCEMENT-v1.md §2/§4) |
| Ceil is not adversary-writable | A_data only | **Assumed.** Discharged only by hardware (§16's in-path ceiling MCU) |

Out of scope: cognitive attacks (genuine EEG from induced states); physical
destruction; the analog scalp–electrode boundary.

## 3. The honest partition — why the architecture has this shape

| Mechanism | Honest evidence | Adversarial forgery |
|---|---|---|
| Detection (all sensors) | Conditional on detector quality | No |
| CTPR propagation | Yes | No — FSI forgeable |
| T4 freshness | Yes | No — clocks host-owned |
| Verdict authenticity | Yes | No — kernel compromisable |
| **T5 consequence bound** | **Yes** | **Yes (vs. A_data)** |

Every row except the last is honest-evidence-conditional. This is the entire
reason the thesis's load-bearing clause is the one after the dash ("...and
the enforcement substrate provably bounds the physical consequence of every
attack the kernel cannot detect") rather than any claim about detection.
Detector quality is not the paper's dependency.

## 4. Consequences traced through the codebase

- `config/claim_registry.json`: every V1 claim declares
  `forgeable_under_A_code: TRUE` — the registry states the honest-evidence
  case for T5 in its own contents, enforced by
  `trust_kernel.schema.validate_claim_registry()` (fail-closed on a missing
  or malformed provenance tuple).
- Per-claim `measurement_source` (`REAL` / `EMULATED_PROTOCOL` / `SIMULATED`)
  and `host_independence` (`SAME_HOST` / `INDEPENDENT_SUBSYSTEM`) record
  *how* honest each producer's evidence is, never *whether* it survives
  A_code — nothing in the registry claims adversarial soundness for any row.
- `sensors/fsi_sensor.py`: FSI attests boot-time state only; an A_code
  attacker who achieves execution after boot can act freely without ever
  touching a PCR, and FSI would keep reporting its trust ceiling. This is
  disclosed in the module docstring and the registry's `provenance_note`,
  not a gap discovered after the fact (see also
  `docs/PHASE10-LATENCY-EVALUATION.md` §4 for why FSI's *cadence* is a
  performance question, not a security one — it follows directly from this
  section: no cadence changes what FSI can or cannot bound under Position A).
- `enforcement/clamp.py`'s five-field boundary (ENFORCEMENT-v1.md §2) is what
  makes T5 provable *despite* full evidence forgery: the enforcer's decision
  path has no field through which a forged verdict's audit trail could
  influence the computed envelope.

## 5. Behaviour-Based Attack Framework (governs Phase B/Phase 11)

Attack experiments must never manipulate trust directly:

```
Attack → Runtime Behaviour → Measured Observations → Evidence → Trust → Policy → Enforcement
```

Directly assigning trust values makes an experiment circular and
scientifically invalid — it would prove the kernel responds to values it was
handed, not that runtime behaviour produces those values through the real
evidence path. Attack categories in scope: replay; signal injection;
adversarial EEG; firmware modification; model replacement; model poisoning;
communication tampering; timing attacks; observer disagreement; actuator
manipulation.

Each attack's results must report three distinct rows, never merged:
reasoning correctness (does CTPR/π produce the expected verdict), detection/
protocol validation (was the attack caught, and by what mechanism), and
consequence-boundedness (does `realise ⊑ Ceil` hold regardless). Attacks with
no detector (training-pipeline poisoning, evidence forgery, in-envelope wrong
command, within-prior calibration poisoning) are reported as
consequence-bounded with no detection claim — per §3's partition, that is the
expected, correct outcome for an honest-evidence-conditional mechanism facing
forgeable evidence, not a gap to be filled by adding a detector.

## 6. Never claimed (restated from CLAUDE.md §1)

Intent verification; end-to-end security; any trust value as a calibrated
probability; SIL certification; clinical readiness; statistical independence
of trust dimensions; BFT.
