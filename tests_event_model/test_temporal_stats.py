"""Tests for event_model/temporal_stats.py. Pure Python, no real-data
dependency -- run via plain python3:
    python3 -m unittest discover -s tests_event_model
"""

import unittest

from event_model import temporal_stats as ts


class LagKAutocorrelationTests(unittest.TestCase):
    def test_perfectly_periodic_lag2_sequence_has_high_lag2_autocorrelation(self):
        x = [1, 0] * 50  # period-2 alternation
        self.assertGreater(ts.lag_k_autocorrelation(x, 2), 0.95)

    def test_perfectly_anti_correlated_lag1_sequence_is_negative(self):
        x = [1, 0] * 50
        self.assertLess(ts.lag_k_autocorrelation(x, 1), -0.9)

    def test_constant_sequence_returns_zero_not_error(self):
        self.assertEqual(ts.lag_k_autocorrelation([5, 5, 5, 5], 1), 0.0)

    def test_rejects_non_positive_k(self):
        with self.assertRaises(ValueError):
            ts.lag_k_autocorrelation([1, 2, 3], 0)

    def test_rejects_k_too_large(self):
        with self.assertRaises(ValueError):
            ts.lag_k_autocorrelation([1, 2, 3], 3)

    def test_hand_computed_exact_value(self):
        # x=[1,2,3,4,5], mean=3, deviations=[-2,-1,0,1,2]
        # num = (-2*-1)+(-1*0)+(0*1)+(1*2) = 2+0+0+2 = 4
        # den = 4+1+0+1+4 = 10 -> ACF(1) = 0.4 exactly
        self.assertAlmostEqual(ts.lag_k_autocorrelation([1, 2, 3, 4, 5], 1), 0.4, places=9)


class RunLengthsTests(unittest.TestCase):
    def test_hand_crafted_sequence(self):
        seq = [0, 1, 1, 0, 0, 1, 0, 1, 1, 1]
        self.assertEqual(ts.run_lengths(seq), [2, 1, 3])

    def test_no_ones_gives_empty(self):
        self.assertEqual(ts.run_lengths([0, 0, 0]), [])

    def test_all_ones_gives_single_run(self):
        self.assertEqual(ts.run_lengths([1, 1, 1]), [3])

    def test_leading_and_trailing_ones(self):
        seq = [1, 1, 0, 1]
        self.assertEqual(ts.run_lengths(seq), [2, 1])


class GapLengthsTests(unittest.TestCase):
    def test_hand_crafted_sequence_internal_gaps_only(self):
        # runs at [1:3), [5:6), [7:10) -> gaps: (3->5)=2, (6->7)=1
        seq = [0, 1, 1, 0, 0, 1, 0, 1, 1, 1]
        self.assertEqual(ts.gap_lengths(seq), [2, 1])

    def test_leading_trailing_zeros_excluded(self):
        seq = [0, 0, 1, 0, 0, 1, 0, 0]
        # runs at [2:3) and [5:6); internal gap = 2; leading/trailing zeros not counted
        self.assertEqual(ts.gap_lengths(seq), [2])

    def test_single_run_gives_no_gaps(self):
        self.assertEqual(ts.gap_lengths([0, 1, 1, 0]), [])

    def test_no_runs_gives_no_gaps(self):
        self.assertEqual(ts.gap_lengths([0, 0, 0]), [])


class GeometricBaselineTests(unittest.TestCase):
    def test_mean_run_length_formula(self):
        self.assertAlmostEqual(ts.geometric_mean_run_length(0.0), 1.0)
        self.assertAlmostEqual(ts.geometric_mean_run_length(0.5), 2.0)

    def test_mean_gap_length_formula(self):
        self.assertAlmostEqual(ts.geometric_mean_gap_length(1.0), 1.0)
        self.assertAlmostEqual(ts.geometric_mean_gap_length(0.1), 10.0)

    def test_pmf_sums_to_one_over_large_support(self):
        alpha = 0.2
        total = sum(ts.geometric_run_length_pmf(alpha, k) for k in range(1, 1000))
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_run_length_pmf_rejects_k_less_than_one(self):
        with self.assertRaises(ValueError):
            ts.geometric_run_length_pmf(0.1, 0)


class PercentileDebounceIntervalTests(unittest.TestCase):
    def test_five_percent_boundary_hand_computed(self):
        # 100 gaps: two of length 1 (2%), rest length 10 (98%).
        # frac_shorter(1) = 0/100 = 0% < 5%
        # frac_shorter(2) = 2/100 = 2% < 5%
        # ... frac_shorter(D) stays 2% for D in [2,10], since no gaps in (1,10)
        # frac_shorter(11) = 100/100 = 100% >= 5% -> D=11
        gaps = [1, 1] + [10] * 98
        self.assertEqual(ts.percentile_debounce_interval(gaps, percentile=5.0), 11)

    def test_geometric_alpha_5pct_gives_small_d(self):
        """Task's own falsification signal: an independent-draw-like gap
        distribution at alpha=5% should yield D in the 1-2 range."""
        import random
        rng = random.Random(0)
        alpha = 0.05
        gaps = []
        for _ in range(20000):
            g = 1
            while rng.random() < (1 - alpha):
                g += 1
            gaps.append(g)
        d = ts.percentile_debounce_interval(gaps, percentile=5.0)
        self.assertIn(d, (1, 2, 3))

    def test_empty_gaps_raises(self):
        with self.assertRaises(ValueError):
            ts.percentile_debounce_interval([])

    def test_rejects_out_of_range_percentile(self):
        with self.assertRaises(ValueError):
            ts.percentile_debounce_interval([1, 2, 3], percentile=0)
        with self.assertRaises(ValueError):
            ts.percentile_debounce_interval([1, 2, 3], percentile=100)


class MergeEpisodesTests(unittest.TestCase):
    def test_close_runs_merge_far_runs_do_not(self):
        # runs at [0:2), [4:6), [20:22) ; gaps = 2, 14
        seq = [1, 1, 0, 0, 1, 1] + [0] * 14 + [1, 1]
        episodes = ts.merge_episodes(seq, debounce_interval=3)
        # gap of 2 < 3 -> merge first two runs into one episode [0,6)
        # gap of 14 >= 3 -> stays separate
        self.assertEqual(episodes, [(0, 6), (20, 22)])

    def test_debounce_interval_one_never_merges(self):
        seq = [1, 0, 1, 0, 1]
        episodes = ts.merge_episodes(seq, debounce_interval=1)
        self.assertEqual(episodes, [(0, 1), (2, 3), (4, 5)])

    def test_large_debounce_interval_merges_everything(self):
        seq = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        episodes = ts.merge_episodes(seq, debounce_interval=100)
        self.assertEqual(episodes, [(0, 9)])

    def test_no_restrictions_gives_no_episodes(self):
        self.assertEqual(ts.merge_episodes([0, 0, 0], debounce_interval=5), [])


class EpisodeStatisticsTests(unittest.TestCase):
    def test_mean_length_and_gap_hand_computed(self):
        episodes = [(0, 2), (5, 6), (20, 25)]  # lengths 2,1,5 ; gaps 3,14
        stats = ts.episode_statistics(episodes, n_windows=30)
        self.assertEqual(stats["n_episodes"], 3)
        self.assertAlmostEqual(stats["mean_episode_length"], (2 + 1 + 5) / 3)
        self.assertAlmostEqual(stats["mean_gap"], (3 + 14) / 2)

    def test_no_episodes(self):
        stats = ts.episode_statistics([], n_windows=100)
        self.assertEqual(stats["n_episodes"], 0)
        self.assertIsNone(stats["mean_episode_length"])


if __name__ == "__main__":
    unittest.main()
