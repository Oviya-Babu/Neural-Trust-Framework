"""Mutation testing harness for sba_validation/ (Phase 8.5). Same
technique and criterion as harnesses/mutation_check.py (CLAUDE.md 12: 100%
kill rate, one full-repository-subset copy per mutant, exercised via
`python3 -m unittest discover -s tests_sba`) -- kept as a SEPARATE harness
rather than folding into mutation_check.py's own MUTANTS/COPY_DIRS, since
sba_validation/ is Phase 8.5 validation tooling, not part of the frozen
pure-core kill-rate suite mutation_check.py exists to guard.

Run: `python3 -m unittest discover -s tests` must still pass unmodified
(sba_validation/ changes nothing there); this harness only touches
sba_validation/ + tests_sba/, reading trust_kernel/ read-only.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

MUTANTS = [
    (
        "sba_validation/probability_model.py",
        "level_low_uses_alpha2_not_alpha",
        "TrustLevel.LOW: alpha,",
        "TrustLevel.LOW: alpha2,",
        "level_distribution: P(LOW) must equal alpha, not alpha2",
    ),
    (
        "sba_validation/probability_model.py",
        "level_high_drops_alpha2",
        "TrustLevel.HIGH: 1 - alpha2,",
        "TrustLevel.HIGH: 1 - alpha,",
        "level_distribution: P(HIGH) must equal 1-alpha2, not 1-alpha",
    ),
    (
        "sba_validation/probability_model.py",
        "generic_ctpr_meet_becomes_assignment",
        "effective[child] = meet(effective[child], ctpr_g(effective[parent]))",
        "effective[child] = ctpr_g(effective[parent])",
        "generic_apply_ctpr must meet with the child's own level, not overwrite it",
    ),
    (
        "sba_validation/probability_model.py",
        "generic_policy_min_becomes_max",
        "return min(crit(d, level, frozenset(strict), frozenset(lenient)) for d, level in effective_dims.items())",
        "return max(crit(d, level, frozenset(strict), frozenset(lenient)) for d, level in effective_dims.items())",
        "generic_policy: pi is a meet (min) over crit_d, not a max",
    ),
    (
        "sba_validation/probability_model.py",
        "enumeration_weight_overwritten_not_multiplied",
        "weight *= level_dist_by_dim[d][level]",
        "weight = level_dist_by_dim[d][level]",
        "exact_window_probabilities: per-dimension probabilities must multiply (joint independence), not overwrite",
    ),
    (
        "sba_validation/probability_model.py",
        "enumeration_verdict_mass_overwritten",
        "verdict_mass[verdict] += weight",
        "verdict_mass[verdict] = weight",
        "exact_window_probabilities: verdict mass must accumulate across combinations, not overwrite",
    ),
    (
        "sba_validation/probability_model.py",
        "p_below_normal_drops_constrained_term",
        '"p_below_normal": verdict_mass[Verdict.Safe] + verdict_mass[Verdict.Constrained],',
        '"p_below_normal": verdict_mass[Verdict.Safe],',
        "p_below_normal must include Constrained, not just Safe",
    ),
    (
        "sba_validation/probability_model.py",
        "naive_p_safe_returns_product_not_complement",
        "    return 1 - p_no_safe",
        "    return p_no_safe",
        "naive_p_safe must return 1 minus the no-failure product",
    ),
    (
        "sba_validation/probability_model.py",
        "naive_p_below_normal_returns_product_not_complement",
        "    return 1 - p_no_restriction",
        "    return p_no_restriction",
        "naive_p_below_normal must return 1 minus the no-restriction product",
    ),
    (
        "sba_validation/probability_model.py",
        "ancestor_closure_ignores_ancestors",
        "        contributing |= set(ancestors)",
        "        pass",
        "corrected_p_safe_with_ancestor_closure must fold in each strict dimension's CTPR ancestors, not just the strict set itself",
    ),
    (
        "sba_validation/probability_model.py",
        "session_to_window_budget_exponent_inverted",
        "return 1 - (1 - session_budget) ** (1 / n_windows)",
        "return 1 - (1 - session_budget) ** n_windows",
        "session_to_window_budget: must take the n_windows-th root, not power",
    ),
    (
        "sba_validation/probability_model.py",
        "flat_split_alpha_exponent_inverted",
        "return 1 - (1 - window_budget) ** (1 / n_claims)",
        "return 1 - (1 - window_budget) ** n_claims",
        "flat_split_alpha: must take the n_claims-th root, not power",
    ),
]

COPY_DIRS = ["sba_validation", "tests_sba", "trust_kernel"]


def _run_suite(root):
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests_sba"],
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
            "baseline tests_sba suite does not pass on unmutated source; "
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

    print(f"SBA mutation kill rate: {killed_count}/{total} ({100 * killed_count // total}%)\n")
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
