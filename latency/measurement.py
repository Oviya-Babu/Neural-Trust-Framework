"""Pure statistics and bounded-wait orchestration for Phase 10's latency
evaluation (CLAUDE.md 7, 14). Zero heavy dependencies (stdlib only),
following the same pattern as event_model/, sba_validation/,
roc_estimability/ -- pure functions, testable and mutation-testable without
real EEG data or real sensor hardware.

percentile()/p50_p99()/stage_overhead()/budget_compliance() are pure
computations over plain lists/dicts of already-measured latency samples (in
milliseconds) -- they never measure anything themselves.

collect_within_deadline() is the one function here that touches real time
and real threads: it is the orchestration primitive that makes CLAUDE.md 7's
"a missing statement is never waited for" property something Phase 10 can
demonstrate directly, not just assert. A task still running when the
deadline elapses is simply absent from the result -- the caller proceeds
with whatever has arrived, exactly as trust_kernel/bands.py's
reduce_dimension() already treats a missing claim (CLAUDE.md 10: "a missing
record is evidence of a problem, not absence of evidence"). This function
does not modify, wrap, or replace anything in trust_kernel/ or
enforcement/ -- it only decides which of several concurrently-running
producer calls get INCLUDED in the statement batch handed to the existing,
unmodified admission/kernel/enforcement code path.
"""

import statistics
import threading
import time


def percentile(samples, p: float) -> float:
    """Nearest-rank percentile over `samples` (not interpolated) -- p in
    [0, 100]. Deterministic, no randomness, matches the convention already
    used by roc_estimability/stability.py's _band_width (index-based, not
    a library call whose interpolation method could silently vary)."""
    if not samples:
        raise ValueError("percentile requires at least one sample")
    if not (0 <= p <= 100):
        raise ValueError("p must be in [0, 100]")
    s = sorted(samples)
    n = len(s)
    idx = min(int(round((p / 100.0) * (n - 1))), n - 1)
    return s[idx]


def p50_p99(samples) -> dict:
    """Summary stats for one stage's latency distribution (milliseconds)."""
    return {
        "n": len(samples),
        "mean_ms": statistics.mean(samples),
        "p50_ms": percentile(samples, 50),
        "p99_ms": percentile(samples, 99),
        "max_ms": max(samples),
        "min_ms": min(samples),
    }


def stage_overhead(baseline_stats: dict, architecture_stats: dict) -> dict:
    """(BCI + architecture) - baseline, per the requested headline
    comparison -- p50 and p99 overhead separately, since tail overhead is
    what actually matters against a fixed-period deadline."""
    return {
        "p50_overhead_ms": architecture_stats["p50_ms"] - baseline_stats["p50_ms"],
        "p99_overhead_ms": architecture_stats["p99_ms"] - baseline_stats["p99_ms"],
        "mean_overhead_ms": architecture_stats["mean_ms"] - baseline_stats["mean_ms"],
    }


def overhead_fraction_of_window(overhead_ms: float, window_period_ms: float = 100.0) -> float:
    """Overhead expressed as a fraction of the 100ms window budget
    (CLAUDE.md 7), the form the headline result must be reported in."""
    if window_period_ms <= 0:
        raise ValueError("window_period_ms must be positive")
    return overhead_ms / window_period_ms


def budget_compliance(measured_p99_ms: float, budget_ms: float) -> dict:
    """Compares a measured p99 against one of CLAUDE.md 7's FROZEN timing
    parameters. Reports the violation; never adjusts the budget to fit the
    measurement (CLAUDE.md 7's own instruction: 'flag any violation rather
    than adjusting the budget')."""
    return {
        "measured_p99_ms": measured_p99_ms,
        "budget_ms": budget_ms,
        "margin_ms": budget_ms - measured_p99_ms,
        "violated": measured_p99_ms > budget_ms,
    }


def collect_within_deadline(tasks: dict, deadline_s: float) -> dict:
    """tasks: {name: zero-arg callable}. Launches each callable in its own
    daemon thread, then waits AT MOST deadline_s in total (not per-task) for
    them to complete. Returns {name: return_value} only for tasks that
    completed successfully within the deadline; a task still running (or
    that raised) when the deadline elapses is simply absent from the
    result -- never retried, never awaited further, matching CLAUDE.md 10's
    "a sensor that cannot measure emits nothing... never a default, never a
    sentinel, never a guess" for the case where it cannot measure IN TIME.
    daemon=True so an abandoned (hung) thread can never block process exit.
    """
    if deadline_s < 0:
        raise ValueError("deadline_s must be non-negative")
    results = {}
    lock = threading.Lock()

    def run(name, fn):
        try:
            value = fn()
        except Exception:
            return  # a raising producer is treated the same as a silent one: absent, not an error verdict
        with lock:
            results[name] = value

    threads = {name: threading.Thread(target=run, args=(name, fn), daemon=True) for name, fn in tasks.items()}
    start = time.perf_counter()
    for t in threads.values():
        t.start()
    for t in threads.values():
        remaining = deadline_s - (time.perf_counter() - start)
        t.join(timeout=max(0.0, remaining))
    with lock:
        return dict(results)
