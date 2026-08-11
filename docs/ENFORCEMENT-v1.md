# Enforcement v1 — Enforcement Plane

Status: **consolidated reference.** Named in CLAUDE.md §11's required `docs/`
layout; did not exist as a standalone document before this pass (Phase A
audit finding, documentation drift, category ii — fixed here). Every claim
below is already established and frozen elsewhere (CLAUDE.md §5/§6,
`enforcement/clamp.py`, `enforcement/capability.py`, `enforcement/slew.py`,
`docs/PHASE5` artifacts); this document adds no new claim.

## 1. What the enforcer is

Dumb, capability-gated actuator writer (CLAUDE.md §2). Produces no evidence
about itself (P2 — the one deliberate exception to "every mechanism generates
evidence," since self-attestation has no evidential weight against an
adversary controlling the attesting component). Its bound (T5) is computed
independently of the verdict.

## 2. The five-field boundary

The enforcer reads **exactly** `schema_version, window_id, verdict,
expires_at, kernel_sig` from a verdict object. It **never** reads
`evidence_root, effective_dims, policy_version, crit_table_hash,
ctpr_config_hash, roc_config_hash, claim_registry_hash, key_registry_hash,
calibration_status, issued_at` — those are audit fields, present in the
signed object, structurally outside the parse-and-act path.

`enforcement/clamp.py`'s `EnforcerView` makes this structural rather than
merely documented: `__slots__ = ENFORCER_FIELDS` means no other attribute can
ever be attached, even by accident. Verified two ways (both real, both re-run
in Phase A): a static grep confirming none of the nine forbidden field names
appear as string literals in `enforcement/`'s source, and a dynamic test
against `EnforcerView` itself. One narrow, understood exception: signature
verification necessarily hashes the *full* signed payload — an opaque,
bytewise operation delegated entirely to `trust_kernel.schema` as a black
box, not a decision that branches on any individual field's meaning.

## 3. `accept()` — acceptance without round knowledge

```
accept(ν) iff sig valid ∧ schema supported
            ∧ ν.window_id ∉ accept_cache        (2-entry ring, expiry horizon)
            ∧ now < ν.expires_at
```

The enforcer never learns "the current round" from any host-controlled
input — `AcceptCache` is a pure recently-seen-window_id ring, not a
round-number comparison. (Kernel-side statement admission *does* check
`window_id == current round`, legitimately, because the kernel opens the
round — CLAUDE.md §6.) Any rejection produces no `EnforcerView` and therefore
no envelope and no actuator write — fail-safe by construction, not by a
separate "write Safe on reject" branch.

## 4. `realise()` — the envelope

```
Φ = (max_speed, max_acceleration)         mm/s, mm/s², fixed-point ints
realise(ν) = Env(π̂(ν)) ⊓ Ceil             meet = componentwise min
```

`Ceil` is loaded once from `config/ceil.json` at process start and is a
parameter to `realise()`, never derived from `verdict_name` or any other
verdict field — `enforcement/clamp.py`'s `realise()` source contains no path
from a verdict object to `ceil`. That independence, not the arithmetic
(`x ⊓ c ⊑ c` is an axiom), is the entire content of T5(a).

Reference values (CLAUDE.md §6 — **labelled REFERENCE, not prescription**,
same status as the illustrative SBA budgets):

| | max_speed | max_acceleration |
|---|---|---|
| Env(Normal) | 1600 | 800 |
| Env(Constrained) | 600 | 300 |
| Env(Safe) | 0 | 0 |
| **Ceil** | **1000** | **500** |

Binding condition, checked at load (`validate_binding()`, fail-closed): Ceil
must be strictly below Env(Normal) in both components, or the clamp never
fires and T5(a) is true-but-empty. Under forced `Normal` (an adversary who
forges everything and gets the kernel to legitimately emit `Normal`):
`realise = (1000, 500)` vs. intended `(1600, 800)` — Figure [T5], quantified.

## 5. Slew

Tightening is immediate/unlimited; loosening is rate-limited (`enforcement/
slew.py`) to ≤200 mm/s and ≤100 mm/s² per window — Safe→full takes 5 windows
= 500ms. This *strengthens* T5: realised envelope ⊆ Env(π) at every
intermediate step, so the T5 bound holds a fortiori through any transition.

## 6. T5 — what it actually says

```
realise(ν) = Env(π̂(ν)) ⊓ Ceil ⊑ Ceil          for all ν, including forged ν
```

T5 must never be proven from π (CLAUDE.md §5). Under Position A the
adversary forges everything, π legitimately returns whatever the forged
evidence produces, and any bound derived *from the verdict's correctness*
would be circular. T5 is a property of `realise()`'s dependency structure —
Ceil is a load-time constant, not a function of ν — verified here by the same
static+dynamic dependency analysis as §2, not by re-deriving it from the
policy logic. Maximum stale actuation under honest timing (§7): 70ms = 7cm at
Ceil speed — the quantified cost of arrival-based freshness under Position A.

## 7. Capability gate

One unforgeable token, held only by the enforcer process, sole write
authority to the actuator (`enforcement/capability.py`). A rejected or failed
verdict never has a token presented to it — there is no envelope object for a
rejected verdict to attach a write to, not a runtime check that happens to
catch it.

## 8. What enforcement is not

Not a reasoning component (P4: enforcer cannot reason, kernel cannot write).
Not adversarially sound against A_code (§3's TA1 table: Ceil's
not-adversary-writable clause is *assumed*, discharged only by hardware — the
in-path ceiling MCU of CLAUDE.md §16, not yet built). Not a safety
certification: T5 bounds consequence, it does not confer safety, and this
project claims no SIL rating.
