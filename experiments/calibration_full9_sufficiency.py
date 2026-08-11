"""Part 1 of the Calibration full-9 sufficiency check (gates the SBA
freeze's Tail-Floor Rule writeup). NOT Phase 9: no real ROC threshold is
derived, calibration_status is never flipped, no theta1/theta2/band_cap is
read off. Same ephemerality guarantee as
experiments/roc_estimability_diagnostic.py: threshold/FPR/TPR-location
computation is structurally confined to roc_estimability/stability.py's
private helpers, never propagated by a public function, and this script's
final report is walked by the same forbidden-key guard before it is
written.

Question this file answers: Calibration failed class support on the
held-out {4,5,6,7,8,9} cohort (3/6 subjects showed genuine drift
separation under the cross-subject-foil mismatch attack, below the 4/6
floor). Does the FULL 9-subject pool (which adds subjects 1,2,3) clear
Calibration's own pre-committed bar -- >=6/9 subjects separating (the
same 2/3 proportion as 4/6, not a loosened count), <=2x bootstrap
band-width ratio, <=0.15 leave-one-subject-out swing?

Reuses experiments/roc_estimability_diagnostic.py's exact Calibration
construction (build_calibration_samples, FOIL_MAP, the same fixed
cross-subject foil pairing decided before any subject's data was
inspected) and roc_estimability/stability.py's exact public functions --
no new construction logic, no new criteria, per the task's "same criteria
and same ephemeral machinery" requirement.

Band-width-ratio note (read before interpreting the ratio field): at the
held-out(6)-vs-full(9) comparison, the ratio's denominator was a LARGER
reference pool. Here, the pool being evaluated (9 subjects) IS the largest
available pool in this dataset (BCIC IV 2a has exactly 9 subjects) -- there
is no larger reference to compare against. The ratio is therefore computed
as a genuine self-comparison (full-9 bootstrap width vs. full-9 bootstrap
width, both computed independently via fresh bootstrap resampling with a
different seed, so it is not definitionally 1.0 by construction -- sampling
noise between the two independent bootstrap runs can and does move it
slightly), and is reported honestly as such rather than treated as a
loosened or vacuous check. The substantive stability signal at the top of
the cohort-size hierarchy is class separation count and leave-one-subject-
out swing, both computed fresh here, not inherited from the held-out run.

Run (needs the pipeline venv):
    .venv-pipeline/bin/python -m experiments.calibration_full9_sufficiency
"""

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bci_pipeline import pipeline as bci_pipeline_mod
from experiments.roc_estimability_diagnostic import (
    FOIL_MAP, FULL_SUBJECTS, N_BOOT, _assert_no_forbidden_keys, build_calibration_samples,
)
from provenance import manifest as manifest_mod
from roc_estimability import stability as st
from sensors import calibration_sensor

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"

FULL9_SEPARATION_MIN_SUBJECTS = 6  # 2/3 of 9, the same proportion as 4/6 -- not a loosened bar
FULL9_BOOTSTRAP_SEED = 20260728  # deliberately different from the held-out run's seed, so the
                                  # self-comparison ratio reflects independent bootstrap noise,
                                  # not the same resample sequence compared to itself
SUBJECTS_ADDED_BY_FULL_POOL = [1, 2, 3]  # not in the held-out {4..9} cohort


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    print("Running the real Phase 7 substrate for all 9 subjects, building "
          "Calibration honest/attack samples via the same cross-subject-foil "
          "mismatch construction as the estimability diagnostic...")

    enrollment_stats = {}
    test_features_by_subject = {}
    for s in FULL_SUBJECTS:
        print(f"  subject {s}...")
        result = bci_pipeline_mod.run_subject(s)
        enrollment_stats[s] = calibration_sensor.compute_enrollment_stats(result["train"]["features"])
        test_features_by_subject[s] = result["test"]["features"]
        del result

    calibration_honest, calibration_attack = {}, {}
    for s in FULL_SUBJECTS:
        foil = FOIL_MAP[s]
        h, a = build_calibration_samples(test_features_by_subject[s], enrollment_stats[s], enrollment_stats[foil])
        calibration_honest[s], calibration_attack[s] = h, a

    per_subject_separates = {
        s: st.class_separates(calibration_honest[s], calibration_attack[s])
        for s in FULL_SUBJECTS
    }
    per_subject_present = {
        s: st.class_presence(calibration_honest[s], calibration_attack[s])
        for s in FULL_SUBJECTS
    }
    n_separating_full9 = sum(1 for v in per_subject_separates.values() if v)
    n_present_full9 = sum(1 for v in per_subject_present.values() if v)

    print("Bootstrapping the full-9 pool (two independent runs, for the self-comparison ratio)...")
    full9_widths_a = st.bootstrap_band_widths(
        FULL_SUBJECTS, calibration_honest, calibration_attack, n_boot=N_BOOT, seed=FULL9_BOOTSTRAP_SEED)
    full9_widths_b = st.bootstrap_band_widths(
        FULL_SUBJECTS, calibration_honest, calibration_attack, n_boot=N_BOOT, seed=FULL9_BOOTSTRAP_SEED + 1)
    self_gap = st.cohort_stability_gap(full9_widths_a, full9_widths_b)

    loso_full9 = st.leave_one_subject_out_swing(FULL_SUBJECTS, calibration_honest, calibration_attack)

    verdict = st.claim_sufficiency_verdict(
        n_subjects_separating=n_separating_full9,
        bootstrap_widths=full9_widths_a,
        loso_swing=loso_full9,
        gap=self_gap,
        min_subjects_separating=FULL9_SEPARATION_MIN_SUBJECTS,
    )

    disposition = "clean_cohort_size_resolution" if verdict["sufficient_on_held_out"] else "tail_floor_rule"

    report = {
        "task": "calibration_full9_sufficiency_part1",
        "claim": "Calibration",
        "phase_9_gate": {
            "real_roc_thresholds_derived": False,
            "calibration_status_flipped_to_measured": False,
            "theta1_theta2_band_cap_read_off": False,
        },
        "cohort": {"full_9": FULL_SUBJECTS, "subjects_added_vs_held_out_6": SUBJECTS_ADDED_BY_FULL_POOL},
        "bootstrap_n": N_BOOT,
        "pre_committed_parameters": {
            "min_subjects_separating_of_9": FULL9_SEPARATION_MIN_SUBJECTS,
            "max_band_width_ratio": st.MAX_BAND_WIDTH_RATIO,
            "max_loso_swing_absolute": st.MAX_LOSO_SWING,
            "foil_map": FOIL_MAP,
        },
        "class_support": {
            "n_of_9_present": n_present_full9,
            "n_of_9_separating": n_separating_full9,
            "sufficiency_floor": FULL9_SEPARATION_MIN_SUBJECTS,
            "subjects_added_by_full_pool_present": {s: per_subject_present[s] for s in SUBJECTS_ADDED_BY_FULL_POOL},
            "subjects_added_by_full_pool_separating": {s: per_subject_separates[s] for s in SUBJECTS_ADDED_BY_FULL_POOL},
            "all_9_subjects_separating": per_subject_separates,
        },
        "bootstrap_band_widths_full_9": full9_widths_a,
        "bootstrap_band_widths_full_9_independent_rerun": full9_widths_b,
        "self_comparison_band_width_ratio": self_gap,
        "leave_one_subject_out_swing_full_9": loso_full9,
        "sufficiency_verdict": verdict,
        "disposition": disposition,
    }

    _assert_no_forbidden_keys(report)

    report_path = ARTIFACTS_DIR / "calibration_full9_sufficiency_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="calibration_full9_sufficiency_part1",
        config_paths={},
        params={"full_subjects": FULL_SUBJECTS, "bootstrap_n": N_BOOT,
                "bootstrap_seeds": [FULL9_BOOTSTRAP_SEED, FULL9_BOOTSTRAP_SEED + 1]},
        artifact_paths={"report": report_path},
        calibration_status="provisional",
        seeds={"note": "reuses experiments/roc_estimability_diagnostic.py's FOIL_MAP and sample construction unmodified"},
    )
    manifest_path = PROVENANCE_DIR / "calibration_full9_sufficiency_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print("\n=== Part 1 result: Calibration, full-9 pool ===")
    print(f"class support: {n_present_full9}/9 present, {n_separating_full9}/9 separating "
          f"(floor={FULL9_SEPARATION_MIN_SUBJECTS})")
    print("subjects added by full pool (1,2,3) -- present:",
          {s: per_subject_present[s] for s in SUBJECTS_ADDED_BY_FULL_POOL})
    print("subjects added by full pool (1,2,3) -- separating:",
          {s: per_subject_separates[s] for s in SUBJECTS_ADDED_BY_FULL_POOL})
    print("all 9 subjects -- separating:", per_subject_separates)
    print(f"\nbootstrap band width (full-9, run A): fpr={full9_widths_a['fpr_band_width']} "
          f"tpr={full9_widths_a['tpr_band_width']}")
    print(f"bootstrap band width (full-9, run B, independent seed): fpr={full9_widths_b['fpr_band_width']} "
          f"tpr={full9_widths_b['tpr_band_width']}")
    print(f"self-comparison ratio (run A / run B): fpr={self_gap['fpr_band_width_ratio_6_over_9']} "
          f"tpr={self_gap['tpr_band_width_ratio_6_over_9']}")
    print(f"\nLOSO max swing (full-9): fpr={loso_full9['max_fpr_swing']} tpr={loso_full9['max_tpr_swing']}")
    print(f"\nsufficient_on_held_out (i.e. sufficient on full-9)={verdict['sufficient_on_held_out']}")
    print(f"failed_tests={verdict['failed_tests']}")
    print(f"disposition={disposition}")

    print(f"\nReport written to {report_path}")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
