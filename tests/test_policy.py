"""Unit tests for trust_kernel/policy.py (CLAUDE.md §4, §5 T2/T3).

Also builds the floor-dominance table (§12 reportable): for every
dimension x every level, crit_d(level) is the floor that dimension alone
imposes, and π(e) must never ⊐ that floor for any e where the dimension
sits at that level. T2 holds by construction (a meet is ⊑ every term of
the meet); this test is a regression guard on that construction (§12: the
check fails only on a dict typo), not an independent empirical validation.
"""

import itertools
import pathlib
import unittest

from trust_kernel import policy as policy_mod
from trust_kernel.bands import DIMENSIONS, TrustLevel
from trust_kernel.policy import Verdict

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"
LEVELS = (TrustLevel.LOW, TrustLevel.MED, TrustLevel.HIGH)


class CritTableValidationTests(unittest.TestCase):
    def test_provisioned_table_loads(self):
        raw, strict, lenient = policy_mod.load_crit_table(CONFIG_DIR / "crit_table.json")
        self.assertEqual(strict | lenient, set(DIMENSIONS))
        self.assertEqual(strict & lenient, frozenset())

    def test_gap_in_partition_rejected(self):
        with self.assertRaises(ValueError):
            policy_mod.validate_crit_table({"strict": ["Signal"], "lenient": ["Device"]})

    def test_overlap_in_partition_rejected(self):
        raw = {"strict": list(DIMENSIONS), "lenient": ["Signal"]}
        with self.assertRaises(ValueError):
            policy_mod.validate_crit_table(raw)

    def test_hash_is_deterministic(self):
        h1 = policy_mod.crit_table_hash(CONFIG_DIR / "crit_table.json")
        h2 = policy_mod.crit_table_hash(CONFIG_DIR / "crit_table.json")
        self.assertEqual(h1, h2)


class FloorDominanceTests(unittest.TestCase):
    """Builds and verifies the floor-dominance table."""

    @classmethod
    def setUpClass(cls):
        cls.raw, cls.strict, cls.lenient = policy_mod.load_crit_table(
            CONFIG_DIR / "crit_table.json"
        )

    def test_strict_dimension_floor_shape(self):
        for d in self.strict:
            self.assertEqual(policy_mod.crit(d, TrustLevel.LOW, self.strict, self.lenient), Verdict.Safe)
            self.assertEqual(policy_mod.crit(d, TrustLevel.MED, self.strict, self.lenient), Verdict.Constrained)
            self.assertEqual(policy_mod.crit(d, TrustLevel.HIGH, self.strict, self.lenient), Verdict.Normal)

    def test_lenient_dimension_floor_shape(self):
        for d in self.lenient:
            self.assertEqual(policy_mod.crit(d, TrustLevel.LOW, self.strict, self.lenient), Verdict.Constrained)
            self.assertEqual(policy_mod.crit(d, TrustLevel.MED, self.strict, self.lenient), Verdict.Constrained)
            self.assertEqual(policy_mod.crit(d, TrustLevel.HIGH, self.strict, self.lenient), Verdict.Normal)

    def test_floor_dominance_over_full_lattice(self):
        """For every dimension d and level ℓ, and every evidence point e
        where effective_d(e) = ℓ, π(e) must be ⊑ crit_d(ℓ). Exhaustive over
        the full 3^6 = 729-point lattice (no CTPR here -- this is π's own
        meet property, independent of propagation)."""
        table = []
        for d in DIMENSIONS:
            for level in LEVELS:
                floor = policy_mod.crit(d, level, self.strict, self.lenient)
                table.append({"dimension": d, "level": level.name, "floor": floor.name})

        self.assertEqual(len(table), 18)  # 6 dimensions x 3 levels
        self.floor_dominance_table = table

        # Exhaustive check: for each dimension fixed at each level, with
        # every OTHER dimension ranging over all 3 levels (3^5 = 243
        # combinations each), verdict must never exceed that dimension's
        # floor.
        other_dims = [d for d in DIMENSIONS]
        for fixed_dim in DIMENSIONS:
            others = [d for d in DIMENSIONS if d != fixed_dim]
            for fixed_level in LEVELS:
                floor = policy_mod.crit(fixed_dim, fixed_level, self.strict, self.lenient)
                for combo in itertools.product(LEVELS, repeat=len(others)):
                    effective = dict(zip(others, combo))
                    effective[fixed_dim] = fixed_level
                    verdict = policy_mod.policy(effective, self.strict, self.lenient)
                    self.assertLessEqual(
                        verdict, floor,
                        f"{fixed_dim}={fixed_level.name} floor={floor.name} "
                        f"but verdict={verdict.name} for {effective}",
                    )


class StaleAndFailSafeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.strict, cls.lenient = policy_mod.load_crit_table(
            CONFIG_DIR / "crit_table.json"
        )

    def test_stale_forces_safe_regardless_of_evidence(self):
        all_high = {d: TrustLevel.HIGH for d in DIMENSIONS}
        self.assertEqual(
            policy_mod.policy(all_high, self.strict, self.lenient, stale=True), Verdict.Safe
        )

    def test_bottom_evidence_is_safe(self):
        """T3: π(⊥) = Safe."""
        bottom = {d: TrustLevel.LOW for d in DIMENSIONS}
        self.assertEqual(policy_mod.policy(bottom, self.strict, self.lenient), Verdict.Safe)

    def test_all_high_evidence_is_normal(self):
        top = {d: TrustLevel.HIGH for d in DIMENSIONS}
        self.assertEqual(policy_mod.policy(top, self.strict, self.lenient), Verdict.Normal)

    def test_missing_dimension_rejected(self):
        incomplete = {d: TrustLevel.HIGH for d in DIMENSIONS if d != "Signal"}
        with self.assertRaises(ValueError):
            policy_mod.policy(incomplete, self.strict, self.lenient)


if __name__ == "__main__":
    unittest.main()
