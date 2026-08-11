"""Phase 8.5 -- SBA (Session Budget Allocation) validation: formal
probability model of honest-operation (non-adversarial) claim false
alarms and their propagation through CTPR to the verdict.

This module does NOT modify, extend, or duplicate trust_kernel/'s
runtime semantics. It reuses trust_kernel.bands / trust_kernel.ctpr /
trust_kernel.policy's real functions directly (apply_ctpr, crit, policy)
so that the "exact enumeration" below is a genuine exercise of the real
implementation, not a hand re-derivation that could silently diverge from
it. It lives outside trust_kernel/ deliberately: this module does floating
-point probability arithmetic for offline session/claim budget planning,
which must never appear in pi's call path (CLAUDE.md 11: "no floats" in
pi's call path) -- this is a planning-time tool, never imported by
trust_kernel/, evidence_plane/, or enforcement/.

Background (see the Phase 8.5 report for the full derivation): under
honest operation, claim d's raw trust level at a window is a random
variable with P(LOW) = alpha_d (by construction of theta1, CLAUDE.md 4:
"theta1 = max{t : FPR(t) <= alpha}") and P(level < HIGH) = alpha2_d (the
FPR realised at theta2, generally >= alpha_d). CTPR (trust_kernel/ctpr.py)
propagates via effective_child = meet(child, g(parent)), currently g =
identity, over the two edges FSI->Signal, FSI->Model.

Central finding (proved in the report, exercised empirically by
experiments/phase8_5_sba_validation.py): for the CURRENT DAG, where the
only CTPR parent (FSI) is itself already a STRICT dimension being unioned
into pi, propagation is an idempotent no-op for both P(Verdict=Safe) and
P(Verdict<Normal) -- the naive flat per-claim allocation is EXACT, not
merely a bound. This ceases to hold only if a future edge propagates from
a dimension NOT already in the same severity class as its child (see
corrected_p_safe_with_ancestor_closure below for the general fallback that
would then be needed).
"""

from itertools import product

from trust_kernel.bands import TrustLevel, meet
from trust_kernel.ctpr import g as ctpr_g
from trust_kernel.policy import Verdict, crit

LEVELS = (TrustLevel.LOW, TrustLevel.MED, TrustLevel.HIGH)


def generic_apply_ctpr(raw_dims: dict, edges) -> dict:
    """Same propagation formula as trust_kernel.ctpr.apply_ctpr
    (effective_child = meet(child, g(parent)), reusing that module's own
    g() and trust_kernel.bands.meet() directly, not reimplemented) but
    generalized over an arbitrary dimension set instead of trust_kernel.
    bands.DIMENSIONS -- apply_ctpr() itself correctly refuses any
    dimension set other than the real deployed six (see
    RealDagMatchesGenericImplementationTests below, which proves this
    function agrees with the real hardcoded one exactly on the real DAG).
    Needed here only to explore hypothetical/boundary-condition DAGs
    (Phase 8.5's cross-severity counterexample) that are not the deployed
    architecture and never will be without a separate PI-approved change
    (CLAUDE.md 18)."""
    effective = dict(raw_dims)
    for parent, child in edges:
        effective[child] = meet(effective[child], ctpr_g(effective[parent]))
    return effective


def generic_policy(effective_dims: dict, strict, lenient) -> Verdict:
    """Same formula as trust_kernel.policy.policy (min over crit_d,
    reusing that module's own crit() directly) but iterating over
    whatever dimensions are actually supplied instead of trust_kernel.
    bands.DIMENSIONS. See generic_apply_ctpr's docstring."""
    return min(crit(d, level, frozenset(strict), frozenset(lenient)) for d, level in effective_dims.items())


def level_distribution(alpha: float, alpha2: float) -> dict:
    """Honest-operation probability mass over {LOW, MED, HIGH} for one
    claim. alpha = P(raw score < theta1) (LOW boundary, CLAUDE.md 4's
    FPR(theta1) <= alpha construction); alpha2 = P(raw score < theta2)
    (the FPR realised at the HIGH boundary; alpha2 >= alpha). band_cap is
    assumed HIGH throughout (a detector that actually attains TPR >=
    1-beta) -- the weak-detector band_cap=MED case is an orthogonal,
    already-covered concern (tests/test_bands.py's DeriveThresholdsTests),
    not remodelled here."""
    if not (0 <= alpha <= alpha2 <= 1):
        raise ValueError(f"require 0 <= alpha <= alpha2 <= 1, got alpha={alpha}, alpha2={alpha2}")
    return {
        TrustLevel.LOW: alpha,
        TrustLevel.MED: alpha2 - alpha,
        TrustLevel.HIGH: 1 - alpha2,
    }


def exact_window_probabilities(dims, level_dist_by_dim, edges, strict, lenient):
    """Enumerates all len(LEVELS)**len(dims) combinations of raw
    per-dimension trust levels, weights each by its probability under
    level_dist_by_dim (dimensions assumed mutually independent -- a
    SEPARATE, explicitly-flagged modelling assumption, orthogonal to the
    CTPR question this module exists to answer), and applies the REAL
    trust_kernel.ctpr.apply_ctpr + trust_kernel.policy.policy functions to
    each combination. Returns the exact resulting distribution over
    Verdict plus the two headline quantities: p_safe (full halt) and
    p_below_normal (any restriction, Constrained-or-worse)."""
    dims = list(dims)
    strict = frozenset(strict)
    lenient = frozenset(lenient)
    if strict | lenient != set(dims):
        raise ValueError("strict/lenient partition must cover exactly `dims`")

    verdict_mass = {Verdict.Safe: 0.0, Verdict.Constrained: 0.0, Verdict.Normal: 0.0}

    for combo in product(LEVELS, repeat=len(dims)):
        raw_dims = dict(zip(dims, combo))
        weight = 1.0
        for d, level in raw_dims.items():
            weight *= level_dist_by_dim[d][level]
        if weight == 0.0:
            continue
        effective = generic_apply_ctpr(raw_dims, edges)
        verdict = generic_policy(effective, strict, lenient)
        verdict_mass[verdict] += weight

    total = sum(verdict_mass.values())
    if abs(total - 1.0) > 1e-9:
        raise AssertionError(f"probability mass does not sum to 1: {total}")

    return {
        "verdict_mass": verdict_mass,
        "p_safe": verdict_mass[Verdict.Safe],
        "p_below_normal": verdict_mass[Verdict.Safe] + verdict_mass[Verdict.Constrained],
    }


def naive_p_safe(alpha_by_strict_dim: dict) -> float:
    """1 - prod_{d in strict}(1-alpha_d): the flat/naive formula, unioning
    ONLY the strict dimensions' own raw-LOW events, with no CTPR-awareness
    at all. Phase 8.5's finding: EXACT (not merely an upper bound) for any
    CTPR DAG whose edges only ever connect a STRICT parent to STRICT
    children -- meet-based propagation is then absorbed by the parent's
    own already-unioned raw-LOW term. See corrected_p_safe_with_ancestor_
    closure for when this stops holding."""
    p_no_safe = 1.0
    for a in alpha_by_strict_dim.values():
        p_no_safe *= (1 - a)
    return 1 - p_no_safe


def naive_p_below_normal(alpha2_by_all_dim: dict) -> float:
    """1 - prod_{d in ALL dims}(1-alpha2_d). Unaffected by CTPR
    UNCONDITIONALLY, for any DAG shape, because crit_d(level) < Normal iff
    level < HIGH for every dimension (strict or lenient alike, per
    trust_kernel/policy.py's crit() tables) -- so meet-based propagation
    can never introduce a level < HIGH that was not already accounted for
    by the parent's own already-unioned level < HIGH term."""
    p_no_restriction = 1.0
    for a2 in alpha2_by_all_dim.values():
        p_no_restriction *= (1 - a2)
    return 1 - p_no_restriction


def corrected_p_safe_with_ancestor_closure(alpha_by_dim: dict, strict, ancestors_of_strict: dict) -> float:
    """General fallback formula (NOT needed for the current deployed DAG
    -- see report): apportions the Safe-budget across the ANCESTOR CLOSURE
    of the strict dimensions in the CTPR DAG, not just the strict
    dimensions themselves. Needed only when some ancestor of a strict
    dimension is not itself already strict (cross-severity propagation,
    e.g. a lenient parent feeding a strict child) -- in that case the
    parent's own ordinary (Constrained-only) failure is severity-escalated
    to Safe via the child's crit_strict table, a genuinely new contributor
    naive_p_safe would miss entirely.

    ancestors_of_strict: {strict_dim: set-of-ancestor-dims-excluding-itself
    that reach it via CTPR edges, regardless of those ancestors' own
    strict/lenient status}.
    """
    contributing = set(strict)
    for _d, ancestors in ancestors_of_strict.items():
        contributing |= set(ancestors)
    p_no_safe = 1.0
    for d in contributing:
        p_no_safe *= (1 - alpha_by_dim[d])
    return 1 - p_no_safe


def session_to_window_budget(session_budget: float, n_windows: int) -> float:
    """Exact solve (not the small-budget linear approximation) of
    p_window from 1-(1-p_window)**n_windows = session_budget, i.e. the
    per-window restriction probability that, applied independently and
    identically across n_windows windows, yields exactly session_budget
    session-level restriction probability. The independent-and-identical-
    across-windows assumption is itself a SEPARATE approximation from the
    CTPR question (see report) -- this function does not touch CTPR at
    all, it only converts a session-level target into a per-window one."""
    if not (0 < session_budget < 1):
        raise ValueError("session_budget must be in (0, 1)")
    if n_windows <= 0:
        raise ValueError("n_windows must be positive")
    return 1 - (1 - session_budget) ** (1 / n_windows)


def flat_split_alpha(window_budget: float, n_claims: int) -> float:
    """Exact solve of per-claim alpha from 1-(1-alpha)**n_claims =
    window_budget -- the 'flat per-claim allocation' this task validates:
    an equal share of the per-window restriction budget handed to each of
    n_claims independently-monitored claims."""
    if not (0 < window_budget < 1):
        raise ValueError("window_budget must be in (0, 1)")
    if n_claims <= 0:
        raise ValueError("n_claims must be positive")
    return 1 - (1 - window_budget) ** (1 / n_claims)
