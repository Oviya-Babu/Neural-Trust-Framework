"""Mutation testing harness for attack_framework/coverage.py (Phase 11's
attack framework). Same technique and criterion as harnesses/mutation_check.py
(CLAUDE.md §12: 100% kill rate), scoped to attack_framework/ + tests_attack_framework/.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

MUTANTS = [
    (
        "attack_framework/coverage.py",
        "detected_true_mechanism_check_disabled",
        "if detected and not (isinstance(detection_mechanism, str) and detection_mechanism):",
        "if False:",
        "build_coverage_row must reject detected=True with no mechanism string",
    ),
    (
        "attack_framework/coverage.py",
        "detected_false_mechanism_check_disabled",
        "if not detected and detection_mechanism is not None:",
        "if False:",
        "build_coverage_row must reject detected=False with a non-None mechanism",
    ),
    (
        "attack_framework/coverage.py",
        "residual_note_check_disabled",
        'if not isinstance(residual_note, str) or not residual_note.strip():',
        "if False:",
        "build_coverage_row must reject an empty/whitespace-only residual_note",
    ),
    (
        "attack_framework/coverage.py",
        "detected_field_dropped_bool_cast",
        '"detected": bool(detected),',
        '"detected": True,',
        "build_coverage_row's 'detected' field must reflect the actual argument, not a constant",
    ),
    (
        "attack_framework/coverage.py",
        "prevented_field_dropped_bool_cast",
        '"prevented": bool(prevented),',
        '"prevented": True,',
        "build_coverage_row's 'prevented' field must reflect the actual argument, not a constant",
    ),
    (
        "attack_framework/coverage.py",
        "consequence_bounded_field_dropped",
        '"consequence_bounded": bool(consequence_bounded),',
        '"consequence_bounded": True,',
        "build_coverage_row's 'consequence_bounded' field must reflect the actual argument, not a constant",
    ),
    (
        "attack_framework/coverage.py",
        "summarize_empty_check_disabled",
        'if not rows:\n        raise ValueError("summarize_coverage requires at least one row")',
        "pass",
        "summarize_coverage must reject an empty row list",
    ),
    (
        "attack_framework/coverage.py",
        "summarize_detected_count_wrong_field",
        'detected = sum(1 for r in rows if r["detected"])',
        'detected = sum(1 for r in rows if r["prevented"])',
        "summarize_coverage's detected_count must count the 'detected' field, not 'prevented'",
    ),
    (
        "attack_framework/coverage.py",
        "summarize_no_detector_count_wrong_formula",
        '"no_detector_count": n - detected,',
        '"no_detector_count": detected,',
        "summarize_coverage's no_detector_count must be (n - detected), not detected itself",
    ),
    (
        "attack_framework/coverage.py",
        "summarize_fraction_wrong_denominator",
        '"consequence_bounded_fraction": consequence_bounded / n,',
        '"consequence_bounded_fraction": consequence_bounded / detected if detected else 0,',
        "summarize_coverage's consequence_bounded_fraction must divide by n (all attacks), not detected count",
    ),
]

COPY_DIRS = ["attack_framework", "tests_attack_framework"]


def _run_suite(root):
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests_attack_framework"],
        cwd=root, capture_output=True, text=True, timeout=120,
    )
    return proc.returncode == 0, proc


def _run_baseline():
    passed, proc = _run_suite(REPO_ROOT)
    if not passed:
        raise SystemExit(
            "baseline tests_attack_framework suite does not pass on unmutated source; "
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

    print(f"attack_coverage mutation kill rate: {killed_count}/{total} ({100 * killed_count // total}%)\n")
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
