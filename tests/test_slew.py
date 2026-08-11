"""Unit tests for enforcement/slew.py (CLAUDE.md §6, §7)."""

import unittest

from enforcement.slew import SlewState, MAX_SPEED_STEP_MM_S, MAX_ACCEL_STEP_MM_S2


class SlewStepSizeGroundTruthTests(unittest.TestCase):
    """Hardcoded independently of the module's own constants -- same class
    of gap as the L-constant / GENESIS_PREV_HASH self-reference fixes."""

    def test_step_sizes_match_claude_md_section_7(self):
        self.assertEqual(MAX_SPEED_STEP_MM_S, 200)
        self.assertEqual(MAX_ACCEL_STEP_MM_S2, 100)


class TighteningTests(unittest.TestCase):
    def test_tightening_is_immediate_and_unlimited(self):
        state = SlewState({"max_speed": 1000, "max_acceleration": 500})
        cmd = state.step({"max_speed": 0, "max_acceleration": 0})
        self.assertEqual(cmd, {"max_speed": 0, "max_acceleration": 0})

    def test_large_tightening_in_one_component_only(self):
        state = SlewState({"max_speed": 1000, "max_acceleration": 500})
        cmd = state.step({"max_speed": 0, "max_acceleration": 500})
        self.assertEqual(cmd, {"max_speed": 0, "max_acceleration": 500})


class LooseningTests(unittest.TestCase):
    def test_loosening_is_rate_limited_per_window(self):
        state = SlewState({"max_speed": 0, "max_acceleration": 0})
        cmd = state.step({"max_speed": 1000, "max_acceleration": 500})
        self.assertEqual(cmd, {"max_speed": 200, "max_acceleration": 100})

    def test_safe_to_full_takes_exactly_five_windows(self):
        """§6/§7: 'Safe→full = 5 windows = 500 ms.'"""
        state = SlewState({"max_speed": 0, "max_acceleration": 0})
        target = {"max_speed": 1000, "max_acceleration": 500}
        speeds = []
        for _ in range(5):
            cmd = state.step(target)
            speeds.append(cmd)
        self.assertEqual(speeds, [
            {"max_speed": 200, "max_acceleration": 100},
            {"max_speed": 400, "max_acceleration": 200},
            {"max_speed": 600, "max_acceleration": 300},
            {"max_speed": 800, "max_acceleration": 400},
            {"max_speed": 1000, "max_acceleration": 500},
        ])

    def test_does_not_overshoot_a_target_closer_than_one_step(self):
        state = SlewState({"max_speed": 950, "max_acceleration": 480})
        cmd = state.step({"max_speed": 1000, "max_acceleration": 500})
        self.assertEqual(cmd, {"max_speed": 1000, "max_acceleration": 500})


class CmdBoundedByTargetInvariantTests(unittest.TestCase):
    def test_cmd_never_exceeds_target_under_oscillating_verdicts(self):
        """cmd ⊑ realise(ν) at every instant (§6), exercised under forced
        Normal<->Safe oscillation (Phase 5 experiment 3)."""
        state = SlewState({"max_speed": 0, "max_acceleration": 0})
        normal = {"max_speed": 1000, "max_acceleration": 500}
        safe = {"max_speed": 0, "max_acceleration": 0}
        for i in range(20):
            target = normal if i % 2 == 0 else safe
            cmd = state.step(target)
            self.assertLessEqual(cmd["max_speed"], target["max_speed"])
            self.assertLessEqual(cmd["max_acceleration"], target["max_acceleration"])


if __name__ == "__main__":
    unittest.main()
