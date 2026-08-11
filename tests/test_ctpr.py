"""CTPR propagation conformance (CLAUDE.md §12: "CTPR 18/18").

Exhaustive over the 2 frozen edges (FSI->Signal, FSI->Model) x 3 FSI levels
x 3 child levels = 18 combinations. Machine-checked implementation
conformance per §12: effective_child = meet(child, g(FSI_level)) is a
two-line formula: the check fails only on a dict/formula typo, not an
independent empirical claim about detector behaviour.
"""

import itertools
import pathlib
import unittest

from trust_kernel import ctpr
from trust_kernel.bands import TrustLevel, DIMENSIONS, meet

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"
LEVELS = (TrustLevel.LOW, TrustLevel.MED, TrustLevel.HIGH)


def _baseline_dims(fsi_level, child_level, child):
    dims = {d: TrustLevel.HIGH for d in DIMENSIONS}
    dims["FSI"] = fsi_level
    dims[child] = child_level
    return dims


class Ctpr18Of18Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.edges = ctpr.load_ctpr_config(CONFIG_DIR / "ctpr.json")

    def test_edges_are_exactly_fsi_to_signal_and_model(self):
        self.assertEqual(set(self.edges), {("FSI", "Signal"), ("FSI", "Model")})

    def test_g_is_the_identity_map(self):
        """Ground truth for g, independent of ctpr.g itself -- if g were
        ever mutated into a constant, this pins the correct behaviour
        without going through the function under test."""
        self.assertEqual(ctpr.g(TrustLevel.LOW), TrustLevel.LOW)
        self.assertEqual(ctpr.g(TrustLevel.MED), TrustLevel.MED)
        self.assertEqual(ctpr.g(TrustLevel.HIGH), TrustLevel.HIGH)

    def test_18_combinations(self):
        # Ground-truth g, hardcoded independently of trust_kernel.ctpr.g:
        # a mutated g must not be able to corrupt this table's own notion
        # of "expected" (mirrors the RFC8032-ground-truth fix in
        # tests/test_sign.py for the analogous self-reference risk).
        ground_truth_g = {
            TrustLevel.LOW: TrustLevel.LOW,
            TrustLevel.MED: TrustLevel.MED,
            TrustLevel.HIGH: TrustLevel.HIGH,
        }
        table = []
        for (parent, child), fsi_level, child_level in itertools.product(
            self.edges, LEVELS, LEVELS
        ):
            raw_dims = _baseline_dims(fsi_level, child_level, child)
            effective = ctpr.apply_ctpr(raw_dims, self.edges)
            expected = meet(child_level, ground_truth_g[fsi_level])
            table.append({
                "edge": f"{parent}->{child}",
                "fsi_level": fsi_level.name,
                "child_level": child_level.name,
                "expected_effective": expected.name,
                "actual_effective": effective[child].name,
                "pass": effective[child] == expected,
            })

        self.assertEqual(len(table), 18, "expected exactly 18 combinations")
        failures = [row for row in table if not row["pass"]]
        self.assertEqual(failures, [], f"CTPR mismatches: {failures}")
        self.ctpr_table = table

    def test_non_edge_dimensions_are_never_touched(self):
        raw_dims = {d: TrustLevel.HIGH for d in DIMENSIONS}
        raw_dims["FSI"] = TrustLevel.LOW
        effective = ctpr.apply_ctpr(raw_dims, self.edges)
        for d in DIMENSIONS:
            if d in ("Signal", "Model", "FSI"):
                continue
            self.assertEqual(effective[d], TrustLevel.HIGH)

    def test_missing_dimension_rejected(self):
        incomplete = {d: TrustLevel.HIGH for d in DIMENSIONS if d != "Calibration"}
        with self.assertRaises(ValueError):
            ctpr.apply_ctpr(incomplete, self.edges)


if __name__ == "__main__":
    unittest.main()
