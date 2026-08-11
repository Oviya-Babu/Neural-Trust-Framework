"""Mutation testing harness for roc_estimability/stability.py (ROC-
estimability diagnostic, prerequisite to Phase 9's cohort decision). Same
technique and criterion as harnesses/mutation_check.py (CLAUDE.md 12: 100%
kill rate) -- kept as a separate harness scoped to roc_estimability/ +
tests_roc_estimability/, no dependency on trust_kernel/ (this module is
pure statistics, like event_model/ and sba_validation/).
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

MUTANTS = [
    (
        "roc_estimability/stability.py",
        "class_presence_only_checks_honest",
        "return len(honest) > 0 and len(attack) > 0",
        "return len(honest) > 0",
        "class_presence must require BOTH classes non-empty, not just honest",
    ),
    (
        "roc_estimability/stability.py",
        "class_separates_comparison_inverted",
        "return (polarity * a) < (polarity * h)",
        "return (polarity * a) > (polarity * h)",
        "class_separates must require the attack median on the MORE attack-like side, not less",
    ),
    (
        "roc_estimability/stability.py",
        "low_tail_threshold_uses_minimum_not_second_smallest",
        "return scored[1]  # strictly above the single minimum score",
        "return scored[0]  # strictly above the single minimum score",
        "_low_tail_threshold must pin above the single minimum honest score (index 1), not at it (index 0)",
    ),
    (
        "roc_estimability/stability.py",
        "fpr_uses_honest_tpr_uses_honest",
        "fpr = sum(1 for v in honest if polarity * v < threshold) / len(honest)\n    tpr = sum(1 for v in attack if polarity * v < threshold) / len(attack)",
        "fpr = sum(1 for v in honest if polarity * v < threshold) / len(honest)\n    tpr = sum(1 for v in honest if polarity * v < threshold) / len(honest)",
        "_fpr_tpr_at's TPR must be computed over the attack samples, not the honest samples again",
    ),
    (
        "roc_estimability/stability.py",
        "band_width_percentile_bounds_swapped",
        "lo = s[int(0.025 * n)]\n    hi = s[min(int(0.975 * n), n - 1)]",
        "lo = s[int(0.975 * n) % n]\n    hi = s[min(int(0.025 * n), n - 1)]",
        "_band_width must use the 2.5th percentile as the low bound and 97.5th as the high bound, not swapped",
    ),
    (
        "roc_estimability/stability.py",
        "n_boot_floor_check_disabled",
        "if n_boot < 1000:",
        "if False:",
        "bootstrap_band_widths must reject n_boot < 1000 per the diagnostic's own requirement",
    ),
    (
        "roc_estimability/stability.py",
        "bootstrap_resample_not_with_replacement",
        "resample = [rng.choice(subject_ids) for _ in subject_ids]",
        "resample = list(subject_ids)",
        "bootstrap_band_widths must resample subjects WITH REPLACEMENT, not just re-use the fixed cohort",
    ),
    (
        "roc_estimability/stability.py",
        "loso_swing_uses_max_not_actual_max",
        "max_fpr_swing = max(max_fpr_swing, abs(fpr - fpr_full))\n        max_tpr_swing = max(max_tpr_swing, abs(tpr - tpr_full))",
        "max_fpr_swing = abs(fpr - fpr_full)\n        max_tpr_swing = abs(tpr - tpr_full)",
        "leave_one_subject_out_swing must track the MAXIMUM swing across all drops, not just the last one",
    ),
    (
        "roc_estimability/stability.py",
        "cohort_gap_ratio_inverted",
        "return a / b",
        "return b / a if a != 0 else None",
        "cohort_stability_gap's ratio must be held-out(6)/full(9) (a/b), not inverted",
    ),
    (
        "roc_estimability/stability.py",
        "sufficiency_class_support_threshold_wrong",
        "if n_subjects_separating < min_subjects_separating:",
        "if n_subjects_separating < 1:",
        "claim_sufficiency_verdict must apply the caller's min_subjects_separating bar, not an arbitrary looser bound",
    ),
    (
        "roc_estimability/stability.py",
        "sufficiency_default_min_subjects_wrong",
        "min_subjects_separating: int = CLASS_SUPPORT_MIN_SUBJECTS) -> dict:",
        "min_subjects_separating: int = 1) -> dict:",
        "claim_sufficiency_verdict's default min_subjects_separating must be CLASS_SUPPORT_MIN_SUBJECTS (4), not an arbitrary looser default",
    ),
    (
        "roc_estimability/stability.py",
        "sufficiency_loso_bound_ignored",
        "if max_fpr_swing is not None and max_fpr_swing > MAX_LOSO_SWING:",
        "if False:",
        "claim_sufficiency_verdict must fail a claim whose LOSO FPR swing exceeds MAX_LOSO_SWING",
    ),
    (
        "roc_estimability/stability.py",
        "sufficiency_verdict_ignores_failures",
        'return {"sufficient_on_held_out": len(failed) == 0, "failed_tests": failed}',
        'return {"sufficient_on_held_out": True, "failed_tests": failed}',
        "claim_sufficiency_verdict must report insufficient whenever any test failed, not unconditionally true",
    ),
]

COPY_DIRS = ["roc_estimability", "tests_roc_estimability"]


def _run_suite(root):
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests_roc_estimability"],
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
            "baseline tests_roc_estimability suite does not pass on unmutated source; "
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

    print(f"roc_estimability mutation kill rate: {killed_count}/{total} ({100 * killed_count // total}%)\n")
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
