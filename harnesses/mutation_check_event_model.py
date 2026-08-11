"""Mutation testing harness for event_model/ (event-counting investigation,
prerequisite to Phase 9). Same technique and criterion as
harnesses/mutation_check.py and harnesses/mutation_check_sba.py (CLAUDE.md
12: 100% kill rate) -- kept as a separate harness scoped to event_model/ +
tests_event_model/, no dependency on trust_kernel/ (this module is pure
statistics, unlike sba_validation/).
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

MUTANTS = [
    (
        "event_model/temporal_stats.py",
        "autocorrelation_denominator_dropped",
        "if den == 0:\n        return 0.0\n    return num / den",
        "return num",
        "lag_k_autocorrelation must normalize by the series variance, not return the raw covariance sum",
    ),
    (
        "event_model/temporal_stats.py",
        "one_runs_start_never_reset",
        "        elif not v and start is not None:\n            runs.append((start, i))\n            start = None",
        "        elif not v and start is not None:\n            runs.append((start, i))",
        "_one_runs must reset `start` after closing a run, or the next run's start is wrong",
    ),
    (
        "event_model/temporal_stats.py",
        "gap_lengths_uses_wrong_endpoints",
        "return [start_next - end_prev for (_, end_prev), (start_next, _) in zip(runs, runs[1:])]",
        "return [start_next - end_prev for (start_next, _), (_, end_prev) in zip(runs, runs[1:])]",
        "gap_lengths must measure from the END of the earlier run to the START of the later one",
    ),
    (
        "event_model/temporal_stats.py",
        "geometric_mean_run_length_wrong_formula",
        "return 1.0 / (1 - alpha)",
        "return 1.0 / alpha",
        "geometric_mean_run_length must be 1/(1-alpha), not 1/alpha (that's the gap formula)",
    ),
    (
        "event_model/temporal_stats.py",
        "geometric_mean_gap_length_wrong_formula",
        "return 1.0 / alpha",
        "return 1.0 / (1 - alpha)",
        "geometric_mean_gap_length must be 1/alpha, not 1/(1-alpha) (that's the run-length formula)",
    ),
    (
        "event_model/temporal_stats.py",
        "debounce_interval_comparison_inverted",
        "if frac_shorter >= threshold_fraction:",
        "if frac_shorter <= threshold_fraction:",
        "percentile_debounce_interval must stop once the shorter-gap fraction REACHES the percentile, not drops below it",
    ),
    (
        "event_model/temporal_stats.py",
        "merge_episodes_comparison_inverted",
        "if gap < debounce_interval:",
        "if gap <= debounce_interval:",
        "merge_episodes: a gap of exactly debounce_interval must NOT merge (task: '< D merge; >= D, two episodes')",
    ),
    (
        "event_model/temporal_stats.py",
        "merge_episodes_end_not_extended",
        "episodes[-1][1] = end",
        "pass",
        "merge_episodes must extend the merged episode's end to the later run's end",
    ),
    (
        "event_model/availability.py",
        "per_window_alpha_exponent_inverted",
        "alpha = 1 - (1 - session_budget) ** (1 / fT)",
        "alpha = 1 - (1 - session_budget) ** fT",
        "per_window_alpha must take the fT-th root, not power",
    ),
    (
        "event_model/availability.py",
        "n_onsets_uses_product_not_sum",
        "cycle_length = mean_episode_length_windows + mean_gap_windows",
        "cycle_length = mean_episode_length_windows * mean_gap_windows",
        "n_onsets_per_session's cycle length is episode+gap, not episode*gap",
    ),
    (
        "event_model/availability.py",
        "episode_alpha_uses_product_not_division",
        "return session_budget / n_onsets",
        "return session_budget * n_onsets",
        "episode_alpha must divide the session budget by n_onsets, not multiply",
    ),
    (
        "event_model/availability.py",
        "representability_boundary_off_by_factor",
        "return alpha * BP_SCALE >= 1.0",
        "return alpha * BP_SCALE >= 0.0",
        "representable_at_current_granularity: the boundary is 1 basis point, not 0",
    ),
]

COPY_DIRS = ["event_model", "tests_event_model"]


def _run_suite(root):
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests_event_model"],
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
            "baseline tests_event_model suite does not pass on unmutated source; "
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

    print(f"event_model mutation kill rate: {killed_count}/{total} ({100 * killed_count // total}%)\n")
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
