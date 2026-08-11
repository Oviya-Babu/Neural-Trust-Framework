"""Mutation testing harness for roc_estimability/threshold_derivation.py
(Phase 9's real, non-ephemeral threshold derivation). Same technique and
criterion as harnesses/mutation_check.py (CLAUDE.md 12: 100% kill rate),
scoped to roc_estimability/ + tests_roc_estimability/ like
harnesses/mutation_check_roc_estimability.py.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

MUTANTS = [
    (
        "roc_estimability/threshold_derivation.py",
        "build_roc_points_empty_honest_check_disabled",
        "if not honest or not attack:",
        "if not attack:",
        "build_roc_points must reject an empty honest list, not just an empty attack list",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "build_roc_points_sentinel_wrong_offset",
        "thresholds = [oriented_all[0] - 1] + oriented_all",
        "thresholds = [oriented_all[0]] + oriented_all",
        "build_roc_points's sentinel threshold must be strictly below the minimum observed score, not equal to it",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "build_roc_points_tpr_uses_honest",
        'fpr = sum(1 for v in honest if polarity * v < t) / n_honest\n        tpr = sum(1 for v in attack if polarity * v < t) / n_attack',
        'fpr = sum(1 for v in honest if polarity * v < t) / n_honest\n        tpr = sum(1 for v in honest if polarity * v < t) / n_honest',
        "build_roc_points's TPR must be computed over attack samples, not honest samples again",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "high_tail_threshold_uses_second_largest",
        "return scored[-1]",
        "return scored[-2]",
        "_high_tail_threshold must pin at the single maximum attack score (index -1), not the second-largest",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "high_tail_fpr_tpr_at_swapped",
        "fpr = sum(1 for v in honest if polarity * v < threshold) / len(honest)\n    tpr = sum(1 for v in attack if polarity * v < threshold) / len(attack)",
        "fpr = sum(1 for v in attack if polarity * v < threshold) / len(attack)\n    tpr = sum(1 for v in honest if polarity * v < threshold) / len(honest)",
        "_fpr_tpr_at must compute FPR over honest and TPR over attack, not swapped",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "high_tail_bootstrap_n_boot_check_disabled",
        "if n_boot < 1000:\n        raise ValueError(\"n_boot must be >= 1000\")",
        "pass",
        "bootstrap_band_widths_high_tail must reject n_boot < 1000",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "high_tail_bootstrap_not_with_replacement",
        "resample = [rng.choice(subject_ids) for _ in subject_ids]",
        "resample = list(subject_ids)",
        "bootstrap_band_widths_high_tail must resample subjects WITH REPLACEMENT",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "high_tail_loso_swing_not_max",
        "max_fpr_swing = max(max_fpr_swing, abs(fpr - fpr_full))\n        max_tpr_swing = max(max_tpr_swing, abs(tpr - tpr_full))",
        "max_fpr_swing = abs(fpr - fpr_full)\n        max_tpr_swing = abs(tpr - tpr_full)",
        "leave_one_subject_out_swing_high_tail must track the MAXIMUM swing, not just the last drop",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "tail_floor_rule_full_pool_check_inverted",
        "is_full_pool = set(cohort_subjects) == set(full_pool_subjects)",
        "is_full_pool = set(cohort_subjects) != set(full_pool_subjects)",
        "evaluate_tail_floor_rule must use the self-comparison gap (1.0) exactly when the cohort IS the full pool, not when it isn't",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "tail_floor_rule_theta1_status_ignores_verdict",
        '"theta1_resolution_status": "stable" if low_verdict["sufficient_on_held_out"] else "tail_floor",',
        '"theta1_resolution_status": "stable",',
        "evaluate_tail_floor_rule's theta1_resolution_status must reflect the actual sufficiency verdict, not be hardcoded stable",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "tail_floor_rule_theta2_status_ignores_verdict",
        '"theta2_resolution_status": "stable" if high_verdict["sufficient_on_held_out"] else "tail_floor",',
        '"theta2_resolution_status": "stable",',
        "evaluate_tail_floor_rule's theta2_resolution_status must reflect the actual sufficiency verdict, not be hardcoded stable",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "derive_operating_point_theta2_applicable_wrong",
        "theta2_applicable = band_cap == TrustLevel.HIGH",
        "theta2_applicable = True",
        "derive_claim_operating_point must only treat theta2 as applicable when band_cap is HIGH (theta2 actually exists)",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "derive_operating_point_ignores_theta1_tail_floor",
        'resolution_status = "tail_floor" if (\n        tail["theta1_resolution_status"] == "tail_floor"\n        or (theta2_applicable and tail["theta2_resolution_status"] == "tail_floor")\n    ) else "stable"',
        'resolution_status = "tail_floor" if (\n        False\n        or (theta2_applicable and tail["theta2_resolution_status"] == "tail_floor")\n    ) else "stable"',
        "derive_claim_operating_point's resolution_status must go tail_floor when theta1 triggers it, not only when theta2 does",
    ),
    (
        "roc_estimability/threshold_derivation.py",
        "derive_operating_point_ignores_theta2_tail_floor_when_applicable",
        'resolution_status = "tail_floor" if (\n        tail["theta1_resolution_status"] == "tail_floor"\n        or (theta2_applicable and tail["theta2_resolution_status"] == "tail_floor")\n    ) else "stable"',
        'resolution_status = "tail_floor" if (\n        tail["theta1_resolution_status"] == "tail_floor"\n        or False\n    ) else "stable"',
        "derive_claim_operating_point's resolution_status must go tail_floor when theta2 triggers it (and theta2 is applicable), not only when theta1 does",
    ),
]

COPY_DIRS = ["roc_estimability", "tests_roc_estimability", "trust_kernel"]


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

    print(f"threshold_derivation mutation kill rate: {killed_count}/{total} ({100 * killed_count // total}%)\n")
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
