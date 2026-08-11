"""Mutation testing harness for the eis.v1 (ppb) representation-widening
addition to trust_kernel/bands.py (prerequisite to Phase 9, CLAUDE.md 12:
100% kill rate). Same technique as harnesses/mutation_check.py (isolated
full-directory-copy-per-mutant) but scoped to the NEW branches this change
introduced: detect_rate_format()'s fail-closed ambiguity/version checks,
the scale-parametric wiring in load_eis_config()/validate_eis_config(),
and representable_at_scale()/representability_margin(). The pre-existing
bands.py mutants (theta1/theta2 boundaries, band(), reduce_dimension(),
etc.) stay in harnesses/mutation_check.py, whose 61/61 kill rate is
confirmed unaffected by this change separately -- this harness does not
duplicate that coverage.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

MUTANTS = [
    (
        "trust_kernel/bands.py",
        "ambiguity_check_only_catches_too_many",
        "if len(present) != 1:",
        "if len(present) > 1:",
        "detect_rate_format must reject BOTH zero and more-than-one alpha fields present, not just more-than-one",
    ),
    (
        "trust_kernel/bands.py",
        "version_disagreement_check_disabled",
        "if declared_version != expected_version:",
        "if False:",
        "detect_rate_format must fail closed when eis_schema_version disagrees with the field format actually used",
    ),
    (
        "trust_kernel/bands.py",
        "declared_version_default_wrong",
        'declared_version = raw.get("eis_schema_version", EIS_SCHEMA_VERSION_V0)',
        'declared_version = raw.get("eis_schema_version", EIS_SCHEMA_VERSION_V1)',
        "a config with no eis_schema_version field must default to V0 (bp/eis.v0), not V1 -- eis.v0.json has no such field",
    ),
    (
        "trust_kernel/bands.py",
        "format_to_schema_version_swapped",
        '_FORMAT_TO_SCHEMA_VERSION = {\n    "bp": EIS_SCHEMA_VERSION_V0,\n    "ppb": EIS_SCHEMA_VERSION_V1,\n}',
        '_FORMAT_TO_SCHEMA_VERSION = {\n    "bp": EIS_SCHEMA_VERSION_V1,\n    "ppb": EIS_SCHEMA_VERSION_V0,\n}',
        "bp must map to schema version 0 and ppb to version 1, not swapped",
    ),
    (
        "trust_kernel/bands.py",
        "load_eis_config_ignores_detected_format",
        'scale, alpha_key, beta_key, fpr_key, tpr_key = _RATE_FORMATS[detect_rate_format(raw)]\n\n    derived = {}',
        'scale, alpha_key, beta_key, fpr_key, tpr_key = _RATE_FORMATS["bp"]\n\n    derived = {}',
        "load_eis_config must use the DETECTED format's scale/keys, not hardcode bp -- eis.v1.json would silently misparse as bp",
    ),
    (
        "trust_kernel/bands.py",
        "validate_eis_config_ignores_detected_format",
        'fmt = detect_rate_format(raw)\n    scale, alpha_key, beta_key, fpr_key, tpr_key = _RATE_FORMATS[fmt]',
        'fmt = detect_rate_format(raw)\n    scale, alpha_key, beta_key, fpr_key, tpr_key = _RATE_FORMATS["bp"]',
        "validate_eis_config must validate ROC points at the DETECTED scale, not hardcode bp",
    ),
    (
        "trust_kernel/bands.py",
        "resolution_status_never_required",
        'requires_resolution_status = fmt != "bp"',
        'requires_resolution_status = False',
        "validate_eis_config must require resolution_status for non-bp (eis.v1+) configs, not skip the check unconditionally",
    ),
    (
        "trust_kernel/bands.py",
        "resolution_status_budget_keys_check_disabled",
        "if set(rs.keys()) != set(SWEPT_BUDGET_LABELS):",
        "if False:",
        "_validate_resolution_status must reject a resolution_status dict with missing/extra budget keys",
    ),
    (
        "trust_kernel/bands.py",
        "resolution_status_value_enum_check_disabled",
        "if value not in RESOLUTION_STATUS_VALUES:",
        "if False:",
        "_validate_resolution_status must reject a value outside {pending, stable, tail_floor}",
    ),
    (
        "trust_kernel/bands.py",
        "representable_at_scale_boundary_off_by_epsilon",
        "return rate * scale >= 1.0",
        "return rate * scale > 1.0",
        "representable_at_scale: the boundary is exactly 1 unit at that scale (>=), not strictly greater than",
    ),
    (
        "trust_kernel/bands.py",
        "representability_margin_wrong_operator",
        "    (1/scale) `rate` clears -- e.g. 130.0 means `rate` is 130x the\n    representability floor at this scale. Purely diagnostic: never fed\n    into any signed or hashed value.\"\"\"\n    return rate * scale",
        "    (1/scale) `rate` clears -- e.g. 130.0 means `rate` is 130x the\n    representability floor at this scale. Purely diagnostic: never fed\n    into any signed or hashed value.\"\"\"\n    return rate + scale",
        "representability_margin must be rate * scale (a multiple of the floor), not rate + scale",
    ),
]

COPY_DIRS = ["trust_kernel", "evidence_plane", "enforcement", "observer", "tests", "config"]


def _run_suite(root):
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
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
            "baseline tests suite does not pass on unmutated source; "
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

    print(f"eis_v1 mutation kill rate: {killed_count}/{total} ({100 * killed_count // total}%)\n")
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
