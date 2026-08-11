"""Tests for event_model/availability.py. Pure Python, no real-data
dependency.
"""

import unittest

from event_model import availability as av


class PerWindowAlphaTests(unittest.TestCase):
    def test_round_trips(self):
        alpha, fT = av.per_window_alpha(0.01, f_hz=10.0, session_hours=8.0)
        self.assertEqual(fT, 288_000)
        recomputed_budget = 1 - (1 - alpha) ** fT
        self.assertAlmostEqual(recomputed_budget, 0.01, places=9)

    def test_smaller_budget_gives_smaller_alpha(self):
        a1, _ = av.per_window_alpha(0.001)
        a2, _ = av.per_window_alpha(0.01)
        self.assertLess(a1, a2)

    def test_rejects_out_of_range_budget(self):
        with self.assertRaises(ValueError):
            av.per_window_alpha(0.0)
        with self.assertRaises(ValueError):
            av.per_window_alpha(1.0)


class NOnsetsPerSessionTests(unittest.TestCase):
    def test_hand_computed(self):
        # cycle = 10 windows, fT = 288000 -> N_onsets = 28800
        n = av.n_onsets_per_session(mean_episode_length_windows=4, mean_gap_windows=6)
        self.assertAlmostEqual(n, 288_000 / 10)

    def test_larger_cycle_gives_fewer_onsets(self):
        n1 = av.n_onsets_per_session(2, 8)
        n2 = av.n_onsets_per_session(2, 800)
        self.assertLess(n2, n1)

    def test_rejects_non_positive_inputs(self):
        with self.assertRaises(ValueError):
            av.n_onsets_per_session(0, 5)
        with self.assertRaises(ValueError):
            av.n_onsets_per_session(5, 0)


class EpisodeAlphaTests(unittest.TestCase):
    def test_hand_computed(self):
        self.assertAlmostEqual(av.episode_alpha(0.01, n_onsets=100), 0.0001)

    def test_fewer_onsets_gives_larger_alpha(self):
        a1 = av.episode_alpha(0.01, n_onsets=1000)
        a2 = av.episode_alpha(0.01, n_onsets=10)
        self.assertGreater(a2, a1)

    def test_rejects_invalid_inputs(self):
        with self.assertRaises(ValueError):
            av.episode_alpha(0.0, n_onsets=10)
        with self.assertRaises(ValueError):
            av.episode_alpha(0.01, n_onsets=0)


class RepresentabilityTests(unittest.TestCase):
    def test_boundary_at_one_basis_point(self):
        self.assertTrue(av.representable_at_current_granularity(1e-4))
        self.assertFalse(av.representable_at_current_granularity(9.99e-5))

    def test_alpha_to_basis_points(self):
        self.assertAlmostEqual(av.alpha_to_basis_points(0.0001), 1.0)
        self.assertAlmostEqual(av.alpha_to_basis_points(0.01), 100.0)


class WindowsNeededForRepresentabilityTests(unittest.TestCase):
    def test_hand_computed_and_consistent_with_episode_alpha(self):
        session_budget = 0.01
        cycle = av.windows_needed_for_representability(target_bp=1.0, session_budget=session_budget)
        # plugging this cycle length back into n_onsets/episode_alpha should
        # land alpha_onset exactly at 1 basis point
        n_onsets = av.n_onsets_per_session(cycle / 2, cycle / 2)  # split arbitrarily; only the sum matters
        alpha = av.episode_alpha(session_budget, n_onsets)
        self.assertAlmostEqual(av.alpha_to_basis_points(alpha), 1.0, places=6)

    def test_rejects_non_positive_budget(self):
        with self.assertRaises(ValueError):
            av.windows_needed_for_representability(session_budget=0)


if __name__ == "__main__":
    unittest.main()
