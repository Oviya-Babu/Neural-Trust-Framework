"""Tests for latency/measurement.py. Pure Python, no real-data dependency:
    python3 -m unittest discover -s tests_latency
"""

import time
import unittest

from latency import measurement as lm


class PercentileTests(unittest.TestCase):
    def test_p50_of_sorted_list(self):
        self.assertEqual(lm.percentile([1, 2, 3, 4, 5], 50), 3)

    def test_p99_of_100_samples(self):
        # nearest-rank over [0..99]: idx = round(0.99*99) = 98 -> value 98
        self.assertEqual(lm.percentile(list(range(100)), 99), 98)

    def test_p0_is_min_p100_is_max(self):
        self.assertEqual(lm.percentile([5, 1, 3], 0), 1)
        self.assertEqual(lm.percentile([5, 1, 3], 100), 5)

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            lm.percentile([], 50)

    def test_out_of_range_p_rejected(self):
        with self.assertRaises(ValueError):
            lm.percentile([1, 2], 101)
        with self.assertRaises(ValueError):
            lm.percentile([1, 2], -1)

    def test_unsorted_input_handled(self):
        self.assertEqual(lm.percentile([9, 1, 5, 3, 7], 50), 5)


class P50P99Tests(unittest.TestCase):
    def test_summary_hand_computed(self):
        stats = lm.p50_p99([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(stats["n"], 5)
        self.assertEqual(stats["mean_ms"], 3.0)
        self.assertEqual(stats["p50_ms"], 3.0)
        self.assertEqual(stats["max_ms"], 5.0)
        self.assertEqual(stats["min_ms"], 1.0)

    def test_p99_reflects_tail_not_mean(self):
        # n=2 makes nearest-rank p99 land exactly on the single outlier
        # (idx = round(0.99*1) = 1), the smallest case that unambiguously
        # demonstrates p99 tracks the tail rather than the mean.
        samples = [1.0, 1000.0]
        stats = lm.p50_p99(samples)
        self.assertEqual(stats["p99_ms"], 1000.0)
        self.assertLess(stats["mean_ms"], stats["p99_ms"])
        self.assertLess(stats["p50_ms"], stats["p99_ms"])


class StageOverheadTests(unittest.TestCase):
    def test_overhead_hand_computed(self):
        baseline = {"p50_ms": 10.0, "p99_ms": 20.0, "mean_ms": 12.0}
        architecture = {"p50_ms": 15.0, "p99_ms": 30.0, "mean_ms": 18.0}
        result = lm.stage_overhead(baseline, architecture)
        self.assertAlmostEqual(result["p50_overhead_ms"], 5.0)
        self.assertAlmostEqual(result["p99_overhead_ms"], 10.0)
        self.assertAlmostEqual(result["mean_overhead_ms"], 6.0)

    def test_negative_overhead_when_architecture_is_faster(self):
        baseline = {"p50_ms": 10.0, "p99_ms": 20.0, "mean_ms": 12.0}
        architecture = {"p50_ms": 8.0, "p99_ms": 18.0, "mean_ms": 10.0}
        result = lm.stage_overhead(baseline, architecture)
        self.assertLess(result["p50_overhead_ms"], 0)


class OverheadFractionTests(unittest.TestCase):
    def test_hand_computed(self):
        self.assertAlmostEqual(lm.overhead_fraction_of_window(5.0, 100.0), 0.05)

    def test_default_window_is_100ms(self):
        self.assertAlmostEqual(lm.overhead_fraction_of_window(10.0), 0.10)

    def test_non_positive_window_rejected(self):
        with self.assertRaises(ValueError):
            lm.overhead_fraction_of_window(5.0, 0.0)
        with self.assertRaises(ValueError):
            lm.overhead_fraction_of_window(5.0, -1.0)


class BudgetComplianceTests(unittest.TestCase):
    def test_within_budget_not_violated(self):
        result = lm.budget_compliance(measured_p99_ms=3.0, budget_ms=5.0)
        self.assertFalse(result["violated"])
        self.assertAlmostEqual(result["margin_ms"], 2.0)

    def test_over_budget_violated(self):
        result = lm.budget_compliance(measured_p99_ms=7.0, budget_ms=5.0)
        self.assertTrue(result["violated"])
        self.assertAlmostEqual(result["margin_ms"], -2.0)

    def test_exact_boundary_not_violated(self):
        result = lm.budget_compliance(measured_p99_ms=5.0, budget_ms=5.0)
        self.assertFalse(result["violated"])


class CollectWithinDeadlineTests(unittest.TestCase):
    def test_fast_tasks_all_collected(self):
        tasks = {"a": lambda: 1, "b": lambda: 2, "c": lambda: 3}
        result = lm.collect_within_deadline(tasks, deadline_s=1.0)
        self.assertEqual(result, {"a": 1, "b": 2, "c": 3})

    def test_hung_task_is_absent_not_waited_for(self):
        def hung():
            time.sleep(5.0)
            return "should never be seen"

        tasks = {"fast": lambda: "ok", "hung": hung}
        start = time.perf_counter()
        result = lm.collect_within_deadline(tasks, deadline_s=0.05)
        elapsed = time.perf_counter() - start

        self.assertEqual(result, {"fast": "ok"})
        self.assertNotIn("hung", result)
        # Bounded by the deadline, not by the hung task's 5s sleep -- this
        # is the actual demonstration, not just an absence check.
        self.assertLess(elapsed, 1.0)

    def test_raising_task_is_absent(self):
        def raises():
            raise RuntimeError("producer failed")

        tasks = {"fast": lambda: "ok", "broken": raises}
        result = lm.collect_within_deadline(tasks, deadline_s=0.2)
        self.assertEqual(result, {"fast": "ok"})
        self.assertNotIn("broken", result)

    def test_multiple_hung_tasks_all_absent_deadline_still_bounded(self):
        def hung():
            time.sleep(5.0)

        tasks = {"h1": hung, "h2": hung, "h3": hung}
        start = time.perf_counter()
        result = lm.collect_within_deadline(tasks, deadline_s=0.05)
        elapsed = time.perf_counter() - start
        self.assertEqual(result, {})
        self.assertLess(elapsed, 1.0)

    def test_deadline_is_a_shared_total_budget_not_reissued_per_task(self):
        """20 hung tasks against a 0.02s deadline: if the deadline were
        (incorrectly) re-granted in full to each task's own join() instead
        of being a shared budget that shrinks as time passes, total elapsed
        could reach 20*0.02s=0.4s -- bound the assertion well below that so
        a per-task-reissued implementation fails it, while a genuinely
        shared budget finishes in close to 0.02s regardless of task count."""
        def hung():
            time.sleep(5.0)

        tasks = {f"h{i}": hung for i in range(20)}
        start = time.perf_counter()
        result = lm.collect_within_deadline(tasks, deadline_s=0.02)
        elapsed = time.perf_counter() - start
        self.assertEqual(result, {})
        self.assertLess(elapsed, 0.2)

    def test_negative_deadline_rejected(self):
        with self.assertRaises(ValueError):
            lm.collect_within_deadline({"a": lambda: 1}, deadline_s=-1.0)

    def test_zero_deadline_excludes_a_task_that_cannot_finish_in_time(self):
        # A near-zero join budget cannot possibly cover a real 0.2s sleep,
        # regardless of thread-scheduling jitter for the fast task.
        def slow():
            time.sleep(0.2)
            return "late"

        tasks = {"slow": slow}
        result = lm.collect_within_deadline(tasks, deadline_s=0.0)
        self.assertNotIn("slow", result)


if __name__ == "__main__":
    unittest.main()
