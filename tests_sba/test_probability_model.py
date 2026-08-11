"""Tests for sba_validation/probability_model.py (Phase 8.5). Pure Python,
no heavy dependencies -- run via plain python3, same as tests/:
    python3 -m unittest discover -s tests_sba
"""

import itertools
import math
import unittest

from trust_kernel.bands import DIMENSIONS, TrustLevel
from trust_kernel.ctpr import apply_ctpr, load_ctpr_config
from trust_kernel.policy import load_crit_table, policy as real_policy
from sba_validation import probability_model as pm

REPO_CONFIG = None


def _real_edges_strict_lenient():
    import pathlib
    config_dir = pathlib.Path(__file__).resolve().parent.parent / "config"
    _, edges = load_ctpr_config(config_dir / "ctpr.json")
    _, strict, lenient = load_crit_table(config_dir / "crit_table.json")
    return edges, strict, lenient


class LevelDistributionTests(unittest.TestCase):
    def test_normalizes_to_one(self):
        d = pm.level_distribution(0.05, 0.2)
        self.assertAlmostEqual(sum(d.values()), 1.0)

    def test_low_equals_alpha_high_equals_one_minus_alpha2(self):
        from trust_kernel.bands import TrustLevel
        d = pm.level_distribution(0.05, 0.2)
        self.assertAlmostEqual(d[TrustLevel.LOW], 0.05)
        self.assertAlmostEqual(d[TrustLevel.HIGH], 0.8)
        self.assertAlmostEqual(d[TrustLevel.MED], 0.15)

    def test_rejects_alpha_greater_than_alpha2(self):
        with self.assertRaises(ValueError):
            pm.level_distribution(0.3, 0.1)

    def test_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            pm.level_distribution(-0.1, 0.2)
        with self.assertRaises(ValueError):
            pm.level_distribution(0.1, 1.5)


class ExactEnumerationTwoIndependentStrictDimsTests(unittest.TestCase):
    """No CTPR edges at all -- exact_window_probabilities must match the
    textbook independent-union formula exactly."""

    def test_p_safe_matches_hand_computed_union(self):
        dims = ["X", "Y"]
        strict, lenient = frozenset(dims), frozenset()
        level_dist = {
            "X": pm.level_distribution(0.10, 0.30),
            "Y": pm.level_distribution(0.05, 0.05),
        }
        result = pm.exact_window_probabilities(dims, level_dist, edges=(), strict=strict, lenient=lenient)
        expected_p_safe = 1 - (1 - 0.10) * (1 - 0.05)
        expected_p_below_normal = 1 - (1 - 0.30) * (1 - 0.05)
        self.assertAlmostEqual(result["p_safe"], expected_p_safe, places=9)
        self.assertAlmostEqual(result["p_below_normal"], expected_p_below_normal, places=9)

    def test_naive_formulas_agree_when_there_is_no_ctpr(self):
        dims = ["X", "Y"]
        strict, lenient = frozenset(dims), frozenset()
        level_dist = {"X": pm.level_distribution(0.10, 0.30), "Y": pm.level_distribution(0.05, 0.05)}
        result = pm.exact_window_probabilities(dims, level_dist, edges=(), strict=strict, lenient=lenient)
        self.assertAlmostEqual(result["p_safe"], pm.naive_p_safe({"X": 0.10, "Y": 0.05}), places=9)
        self.assertAlmostEqual(
            result["p_below_normal"], pm.naive_p_below_normal({"X": 0.30, "Y": 0.05}), places=9
        )


class RealDagIdempotenceTests(unittest.TestCase):
    """The central Phase 8.5 finding: for the DEPLOYED DAG (FSI->Signal,
    FSI->Model, all three strict), CTPR provably does not change the
    per-window p_safe or p_below_normal versus the naive/flat formula --
    exactly, not approximately. Verified here at several alpha regimes,
    including a stress case where FSI's own alpha is NOT small relative to
    the others (the idempotence proof has no small-alpha requirement)."""

    def _check(self, alpha_by_dim, alpha2_by_dim):
        edges, strict, lenient = _real_edges_strict_lenient()
        level_dist = {d: pm.level_distribution(alpha_by_dim[d], alpha2_by_dim[d]) for d in DIMENSIONS}
        exact = pm.exact_window_probabilities(DIMENSIONS, level_dist, edges, strict, lenient)

        alpha_strict = {d: a for d, a in alpha_by_dim.items() if d in strict}
        naive_safe = pm.naive_p_safe(alpha_strict)
        naive_below_normal = pm.naive_p_below_normal(alpha2_by_dim)

        self.assertAlmostEqual(exact["p_safe"], naive_safe, places=9)
        self.assertAlmostEqual(exact["p_below_normal"], naive_below_normal, places=9)
        return exact, naive_safe, naive_below_normal

    def test_small_uniform_alpha(self):
        alpha = {d: 0.001 for d in DIMENSIONS}
        alpha2 = {d: 0.004 for d in DIMENSIONS}
        self._check(alpha, alpha2)

    def test_fsi_alpha_much_larger_than_others_still_exact(self):
        """Stress case: FSI's own alpha is an order of magnitude larger
        than the other claims'. If the idempotence result were only a
        small-alpha approximation, this case would expose a gap; the
        proof has no such requirement, so it must still match exactly."""
        alpha = {d: 0.001 for d in DIMENSIONS}
        alpha["FSI"] = 0.30
        alpha2 = {d: 0.004 for d in DIMENSIONS}
        alpha2["FSI"] = 0.55
        self._check(alpha, alpha2)

    def test_realistic_tiny_alpha_regime(self):
        alpha = {d: 1e-8 for d in DIMENSIONS}
        alpha2 = {d: 4e-8 for d in DIMENSIONS}
        self._check(alpha, alpha2)

    def test_ctpr_on_vs_off_produce_identical_p_safe_and_p_below_normal(self):
        """Direct on/off contrast using the exact same enumeration code
        path, isolating CTPR as the only variable."""
        edges, strict, lenient = _real_edges_strict_lenient()
        alpha = {d: 0.01 for d in DIMENSIONS}
        alpha["FSI"] = 0.05
        alpha2 = {d: 0.03 for d in DIMENSIONS}
        alpha2["FSI"] = 0.12
        level_dist = {d: pm.level_distribution(alpha[d], alpha2[d]) for d in DIMENSIONS}

        with_ctpr = pm.exact_window_probabilities(DIMENSIONS, level_dist, edges, strict, lenient)
        without_ctpr = pm.exact_window_probabilities(DIMENSIONS, level_dist, (), strict, lenient)

        self.assertAlmostEqual(with_ctpr["p_safe"], without_ctpr["p_safe"], places=9)
        self.assertAlmostEqual(with_ctpr["p_below_normal"], without_ctpr["p_below_normal"], places=9)


class CrossSeverityBoundaryCaseTests(unittest.TestCase):
    """The general concern IS valid -- just not for the deployed DAG. A
    hypothetical lenient-parent -> strict-child edge (NOT the current
    architecture) breaks the idempotence result for p_safe specifically,
    and naive_p_safe must be shown failing here while
    corrected_p_safe_with_ancestor_closure passes -- the naive-fails/
    derived-passes contrast the task requires."""

    def setUp(self):
        self.dims = ["P", "C"]
        self.strict = frozenset(["C"])
        self.lenient = frozenset(["P"])
        self.edges = (("P", "C"),)
        self.alpha = {"P": 0.10, "C": 0.02}
        self.alpha2 = {"P": 0.20, "C": 0.05}
        self.level_dist = {d: pm.level_distribution(self.alpha[d], self.alpha2[d]) for d in self.dims}

    def test_naive_p_safe_underestimates(self):
        exact = pm.exact_window_probabilities(self.dims, self.level_dist, self.edges, self.strict, self.lenient)
        naive = pm.naive_p_safe({"C": self.alpha["C"]})  # naive: only strict dims counted, P excluded
        self.assertLess(naive, exact["p_safe"])
        # exact hand-computation: P(L_C=LOW or L_P=LOW) = 1-(1-0.02)(1-0.10)
        expected_exact = 1 - (1 - 0.02) * (1 - 0.10)
        self.assertAlmostEqual(exact["p_safe"], expected_exact, places=9)
        self.assertAlmostEqual(naive, 0.02, places=9)

    def test_corrected_ancestor_closure_formula_matches_exact(self):
        exact = pm.exact_window_probabilities(self.dims, self.level_dist, self.edges, self.strict, self.lenient)
        corrected = pm.corrected_p_safe_with_ancestor_closure(
            self.alpha, self.strict, ancestors_of_strict={"C": {"P"}}
        )
        self.assertAlmostEqual(corrected, exact["p_safe"], places=9)

    def test_p_below_normal_still_unaffected_even_in_cross_severity_case(self):
        """p_below_normal's robustness (crit_d(level) < Normal iff level <
        HIGH for every dimension) does not depend on same-severity
        propagation at all -- must still hold here."""
        exact = pm.exact_window_probabilities(self.dims, self.level_dist, self.edges, self.strict, self.lenient)
        naive = pm.naive_p_below_normal(self.alpha2)
        self.assertAlmostEqual(exact["p_below_normal"], naive, places=9)


class BudgetConversionTests(unittest.TestCase):
    def test_session_to_window_budget_round_trips(self):
        session_budget = 0.01
        n_windows = 288_000
        p_window = pm.session_to_window_budget(session_budget, n_windows)
        recomputed_session_budget = 1 - (1 - p_window) ** n_windows
        self.assertAlmostEqual(recomputed_session_budget, session_budget, places=9)

    def test_flat_split_alpha_round_trips(self):
        window_budget = 1e-6
        n_claims = 5
        alpha = pm.flat_split_alpha(window_budget, n_claims)
        recomputed_window_budget = 1 - (1 - alpha) ** n_claims
        self.assertAlmostEqual(recomputed_window_budget, window_budget, places=12)

    def test_smaller_session_budget_yields_smaller_window_budget(self):
        p1 = pm.session_to_window_budget(0.001, 288_000)
        p2 = pm.session_to_window_budget(0.01, 288_000)
        self.assertLess(p1, p2)

    def test_rejects_out_of_range_session_budget(self):
        with self.assertRaises(ValueError):
            pm.session_to_window_budget(0.0, 100)
        with self.assertRaises(ValueError):
            pm.session_to_window_budget(1.0, 100)

    def test_rejects_non_positive_n_windows(self):
        with self.assertRaises(ValueError):
            pm.session_to_window_budget(0.01, 0)


class GenericImplementationMatchesRealHardcodedFunctionsTests(unittest.TestCase):
    """probability_model.generic_apply_ctpr / generic_policy exist only
    because trust_kernel.ctpr.apply_ctpr / trust_kernel.policy.policy
    correctly refuse any dimension set other than the real deployed six
    (by design -- that refusal is itself a fail-closed property, not a
    limitation to route around). This test proves the generic versions,
    used for exact_window_probabilities' 3**6 enumeration, produce
    IDENTICAL verdicts to the real, unmodified, hardcoded functions across
    every one of the 729 raw-level combinations -- so the exact-
    enumeration results reported for the real DAG are genuinely backed by
    the real kernel code, not merely a hopefully-equivalent reimplementation."""

    def test_all_729_combinations_agree_with_real_apply_ctpr_and_policy(self):
        edges, strict, lenient = _real_edges_strict_lenient()
        levels = (TrustLevel.LOW, TrustLevel.MED, TrustLevel.HIGH)
        mismatches = []
        for combo in itertools.product(levels, repeat=len(DIMENSIONS)):
            raw_dims = dict(zip(DIMENSIONS, combo))
            real_effective = apply_ctpr(raw_dims, edges)
            real_verdict = real_policy(real_effective, strict, lenient)
            generic_effective = pm.generic_apply_ctpr(raw_dims, edges)
            generic_verdict = pm.generic_policy(generic_effective, strict, lenient)
            if real_verdict != generic_verdict or real_effective != generic_effective:
                mismatches.append((raw_dims, real_verdict, generic_verdict))
        self.assertEqual(mismatches, [], f"{len(mismatches)} of 729 combinations disagreed")


class ExactEnumerationMassSumTests(unittest.TestCase):
    def test_full_real_dag_probability_mass_sums_to_one(self):
        edges, strict, lenient = _real_edges_strict_lenient()
        level_dist = {d: pm.level_distribution(0.02, 0.06) for d in DIMENSIONS}
        result = pm.exact_window_probabilities(DIMENSIONS, level_dist, edges, strict, lenient)
        total = sum(result["verdict_mass"].values())
        self.assertAlmostEqual(total, 1.0, places=9)


if __name__ == "__main__":
    unittest.main()
