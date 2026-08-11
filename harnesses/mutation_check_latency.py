"""Mutation testing harness for latency/measurement.py (Phase 10's latency
evaluation). Same technique and criterion as harnesses/mutation_check.py
(CLAUDE.md 12: 100% kill rate), scoped to latency/ + tests_latency/.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

MUTANTS = [
    (
        "latency/measurement.py",
        "percentile_range_check_disabled",
        "if not (0 <= p <= 100):",
        "if False:",
        "percentile must reject p outside [0, 100]",
    ),
    (
        "latency/measurement.py",
        "percentile_empty_check_disabled",
        "if not samples:\n        raise ValueError(\"percentile requires at least one sample\")",
        "pass",
        "percentile must reject an empty sample list",
    ),
    (
        "latency/measurement.py",
        "percentile_index_formula_wrong",
        "idx = min(int(round((p / 100.0) * (n - 1))), n - 1)",
        "idx = min(int(round((p / 100.0) * n)), n - 1)",
        "percentile's nearest-rank index must scale by (n-1), not n",
    ),
    (
        "latency/measurement.py",
        "p50_p99_uses_wrong_percentile_for_p99",
        '"p99_ms": percentile(samples, 99),',
        '"p99_ms": percentile(samples, 50),',
        "p50_p99 must compute the 99th percentile for p99_ms, not the 50th again",
    ),
    (
        "latency/measurement.py",
        "stage_overhead_p99_uses_p50",
        '"p99_overhead_ms": architecture_stats["p99_ms"] - baseline_stats["p99_ms"],',
        '"p99_overhead_ms": architecture_stats["p50_ms"] - baseline_stats["p50_ms"],',
        "stage_overhead's p99_overhead_ms must compare p99 fields, not p50",
    ),
    (
        "latency/measurement.py",
        "stage_overhead_direction_inverted",
        '"p50_overhead_ms": architecture_stats["p50_ms"] - baseline_stats["p50_ms"],',
        '"p50_overhead_ms": baseline_stats["p50_ms"] - architecture_stats["p50_ms"],',
        "stage_overhead must be (architecture - baseline), not the reverse",
    ),
    (
        "latency/measurement.py",
        "overhead_fraction_wrong_operator",
        "return overhead_ms / window_period_ms",
        "return overhead_ms * window_period_ms",
        "overhead_fraction_of_window must divide by the window period, not multiply",
    ),
    (
        "latency/measurement.py",
        "overhead_fraction_nonpositive_check_disabled",
        "if window_period_ms <= 0:",
        "if False:",
        "overhead_fraction_of_window must reject a non-positive window period",
    ),
    (
        "latency/measurement.py",
        "budget_compliance_comparison_inverted",
        '"violated": measured_p99_ms > budget_ms,',
        '"violated": measured_p99_ms < budget_ms,',
        "budget_compliance must flag violated when measured EXCEEDS budget, not when it's under",
    ),
    (
        "latency/measurement.py",
        "budget_compliance_margin_inverted",
        '"margin_ms": budget_ms - measured_p99_ms,',
        '"margin_ms": measured_p99_ms - budget_ms,',
        "budget_compliance's margin must be budget minus measured, not the reverse",
    ),
    (
        "latency/measurement.py",
        "collect_within_deadline_negative_check_disabled",
        "if deadline_s < 0:\n        raise ValueError(\"deadline_s must be non-negative\")",
        "pass",
        "collect_within_deadline must reject a negative deadline",
    ),
    (
        "latency/measurement.py",
        "collect_within_deadline_ignores_exceptions_incorrectly",
        "except Exception:\n            return  # a raising producer is treated the same as a silent one: absent, not an error verdict",
        "except Exception:\n            with lock:\n                results[name] = None",
        "collect_within_deadline must leave a raising task's name OUT of the result, not record None for it",
    ),
    (
        "latency/measurement.py",
        "collect_within_deadline_shared_budget_not_per_task",
        "remaining = deadline_s - (time.perf_counter() - start)",
        "remaining = deadline_s",
        "collect_within_deadline must spend a SHARED total deadline across all tasks, not re-grant the full deadline to each",
    ),
]

COPY_DIRS = ["latency", "tests_latency"]


def _run_suite(root):
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests_latency"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode == 0, proc


def _run_baseline():
    passed, proc = _run_suite(REPO_ROOT)
    if not passed:
        raise SystemExit(
            "baseline tests_latency suite does not pass on unmutated source; "
            "fix tests before running mutation analysis\n" + proc.stdout + proc.stderr
        )


def main():
    _run_baseline()

    results = []
    for target, name, old, new, prop in MUTANTS:
        target_path = REPO_ROOT / target
        source = target_path.read_text()
        if old not in source:
            raise SystemExit(f"mutant '{name}': anchor text not found in {target} (source drifted)")
        mutated_source = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            for d in COPY_DIRS:
                shutil.copytree(REPO_ROOT / d, tmp_path / d)
            (tmp_path / target).write_text(mutated_source)

            passed, proc = _run_suite(tmp_path)
            killed = not passed
            killing_tests = _extract_failed_tests(proc.stderr) if killed else []
            results.append((target, name, prop, killed, killing_tests))

    total = len(results)
    killed_count = sum(1 for *_, killed, _ in results if killed)

    print(f"latency mutation kill rate: {killed_count}/{total} ({100 * killed_count // total}%)\n")
    for target, name, prop, killed, killing_tests in results:
        status = "KILLED  " if killed else "SURVIVED"
        print(f"  [{status}] {name}  ({prop})")
        if killed:
            for t in killing_tests:
                print(f"             caught by: {t}")
        else:
            print("             *** no test asserts this property ***")

    if killed_count < total:
        sys.exit(1)


def _extract_failed_tests(stderr):
    names = []
    for line in stderr.splitlines():
        line = line.strip()
        if line.startswith("FAIL:") or line.startswith("ERROR:"):
            names.append(line.split(" ", 1)[1].split(" ")[0])
    return names


if __name__ == "__main__":
    main()
