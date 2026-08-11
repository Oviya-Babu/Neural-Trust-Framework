"""T1 (CLAUDE.md §5): e ⊑ e' ⟹ π(e) ⊑ π(e'), for the full composed pipeline
ctpr -> policy, over the entire 3^6 = 729-point evidence lattice.

This is machine-checked implementation conformance, not independent
empirical validation (§12): π is constructed as a meet of monotone maps
(crit_d is a hand-verified order-preserving 3-point table; CTPR's
meet(child, g(parent)) is monotone in both arguments), so monotonicity
holds by a one-line lattice-theory argument -- "⊓-of-monotone-maps-is-
monotone is a theorem; the check fails only on a dict typo" (§12). This
test is that regression guard, not a claim about detector behaviour.

Exhaustive-over-covering-relations, not all C(729,2) pairs: checking
π(e) ⊑ π(e') for every pair where e' differs from e by bumping exactly one
dimension up by one level implies π(e) ⊑ π(e') for EVERY comparable pair
(e ⊑ e'), by transitivity of ⊑ along the covering chain connecting them.
This still covers the entire lattice -- it is a tractability choice, not a
weaker sample.
"""

import itertools
import pathlib
import unittest

from trust_kernel import ctpr as ctpr_mod
from trust_kernel import policy as policy_mod
from trust_kernel.bands import DIMENSIONS, TrustLevel

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"
LEVELS = (TrustLevel.LOW, TrustLevel.MED, TrustLevel.HIGH)


def _pi(raw_dims, edges, strict, lenient):
    effective = ctpr_mod.apply_ctpr(raw_dims, edges)
    return policy_mod.policy(effective, strict, lenient)


class LatticeMonotonicityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.edges = ctpr_mod.load_ctpr_config(CONFIG_DIR / "ctpr.json")
        _, cls.strict, cls.lenient = policy_mod.load_crit_table(CONFIG_DIR / "crit_table.json")

    def test_full_lattice_size_is_729(self):
        count = sum(1 for _ in itertools.product(LEVELS, repeat=len(DIMENSIONS)))
        self.assertEqual(count, 729)

    def test_covering_relations_are_monotone_across_full_lattice(self):
        checked = 0
        violations = []
        for combo in itertools.product(LEVELS, repeat=len(DIMENSIONS)):
            base = dict(zip(DIMENSIONS, combo))
            pi_base = _pi(base, self.edges, self.strict, self.lenient)
            for d in DIMENSIONS:
                if base[d] == TrustLevel.HIGH:
                    continue
                bumped = dict(base)
                bumped[d] = TrustLevel(base[d] + 1)
                pi_bumped = _pi(bumped, self.edges, self.strict, self.lenient)
                checked += 1
                if pi_bumped < pi_base:
                    violations.append((base, d, pi_base.name, pi_bumped.name))

        self.assertEqual(checked, 729 * 6 - sum(
            1 for combo in itertools.product(LEVELS, repeat=len(DIMENSIONS))
            for d in DIMENSIONS if dict(zip(DIMENSIONS, combo))[d] == TrustLevel.HIGH
        ))
        self.assertEqual(violations, [], f"monotonicity violations: {violations[:5]} (+{max(0,len(violations)-5)} more)")
        self.monotonicity_checked_pairs = checked

    def test_bottom_and_top_are_endpoints_of_the_verdict_chain(self):
        bottom = {d: TrustLevel.LOW for d in DIMENSIONS}
        top = {d: TrustLevel.HIGH for d in DIMENSIONS}
        self.assertEqual(_pi(bottom, self.edges, self.strict, self.lenient), policy_mod.Verdict.Safe)
        self.assertEqual(_pi(top, self.edges, self.strict, self.lenient), policy_mod.Verdict.Normal)


if __name__ == "__main__":
    unittest.main()
