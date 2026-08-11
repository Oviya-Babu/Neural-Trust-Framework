"""Event-counting investigation (prerequisite to Phase 9). Establishes,
empirically against the real unmodified pipeline (real bands/CTPR/policy,
real bci_pipeline substrate, real sensors.signal_sensor /
sensors.calibration_sensor, honest operation, real subject data -- no
synthetic or placeholder verdicts), whether the per-window independence
assumption behind Phase 8.5's SBA formula holds, and whether an
episode/onset-counted alternative is (a) mathematically warranted and
(b) practically representable at the current basis-point config
granularity.

Explicitly NOT done here (per the task): no real ROC/threshold derivation
(no attack data is used anywhere in this investigation -- only honest
operation), no modification to the wire/statement schema, no change to
CLAUDE.md, no start of Phase 9.

Run: `.venv-pipeline/bin/python -m experiments.event_model_investigation`
(needs bci_pipeline/ + sensors/ real dependencies; ~2 minutes per subject).
"""

import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from bci_pipeline import loader as bci_loader
from event_model import availability as av
from event_model import continuous_stream as cs
from event_model import temporal_stats as ts
from provenance import manifest as manifest_mod

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"

SUBJECTS = [1, 2, 3]
PERCENTILES = [5.0, 1.0]  # primary=5% (matches the pre-committed debounce percentile), secondary=1% (matches SBA's nominal budget)
DEBOUNCE_PERCENTILE = 5.0  # PRE-COMMITTED, fixed before looking at data (task Step 2)
SESSION_BUDGETS = [0.001, 0.01, 0.05]  # 0.1%, 1%, 5% -- illustrative research parameters only
LAGS_TO_REPORT = [1, 2, 5, 10, 50]

CLAIMS = ("Signal", "Calibration")


def _write_json(obj, path):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def _restricted_indicator(raw_values: np.ndarray, percentile: float) -> tuple:
    """A window is 'restricted' (LOW-band, by this investigation's
    illustrative percentile-based operating point) if its raw_measurement
    is at or below the `percentile`-th percentile of the OBSERVED
    distribution -- purely an empirical operating-point choice for
    characterizing temporal structure (NOT an ROC/attack-derived
    threshold: no attack data is used anywhere in this investigation).
    Both Signal and Calibration have expected polarity +1 (higher =
    healthier, sensors/signal_sensor.py, sensors/calibration_sensor.py),
    so the LOW/restricted tail is the LOW-percentile tail."""
    threshold = float(np.percentile(raw_values, percentile))
    restricted = (raw_values <= threshold).astype(int)
    return restricted, threshold


def _claim_temporal_analysis(raw_values: np.ndarray, percentile: float) -> dict:
    restricted, threshold = _restricted_indicator(raw_values, percentile)
    restricted_list = restricted.tolist()
    n = len(restricted_list)

    raw_autocorr = {k: ts.lag_k_autocorrelation(raw_values.tolist(), k) for k in LAGS_TO_REPORT}
    binary_autocorr = {k: ts.lag_k_autocorrelation(restricted_list, k) for k in LAGS_TO_REPORT}

    runs = ts.run_lengths(restricted_list)
    gaps = ts.gap_lengths(restricted_list)

    alpha_implied = percentile / 100.0
    predicted_mean_run = ts.geometric_mean_run_length(alpha_implied)
    predicted_mean_gap = ts.geometric_mean_gap_length(alpha_implied)

    measured_mean_run = float(np.mean(runs)) if runs else None
    measured_mean_gap = float(np.mean(gaps)) if gaps else None

    return {
        "percentile": percentile, "threshold_raw_measurement": threshold,
        "n_windows": n, "n_restricted_windows": int(restricted.sum()),
        "observed_restricted_fraction": float(restricted.mean()),
        "raw_series_autocorrelation": raw_autocorr,
        "binary_indicator_autocorrelation": binary_autocorr,
        "n_runs": len(runs), "n_gaps": len(gaps),
        "measured_mean_run_length": measured_mean_run,
        "predicted_mean_run_length_independent": predicted_mean_run,
        "run_length_ratio_measured_over_predicted": (measured_mean_run / predicted_mean_run) if measured_mean_run else None,
        "measured_mean_gap_length": measured_mean_gap,
        "predicted_mean_gap_length_independent": predicted_mean_gap,
        "gap_ratio_measured_over_predicted": (measured_mean_gap / predicted_mean_gap) if measured_mean_gap else None,
        "restricted_indicator": restricted_list,
        "runs": runs, "gaps": gaps,
    }


def falsification_verdict(claim_analysis: dict) -> dict:
    """The task's falsification requirement, made explicit and mechanical
    rather than a judgment call buried in prose: weak autocorrelation
    (|lag-1| below a fixed, pre-stated bound) AND run lengths close to the
    independent-draw geometric prediction (ratio near 1) together
    constitute falsification of the practical episode-counting case for
    THIS claim at THIS operating point."""
    lag1 = claim_analysis["binary_indicator_autocorrelation"].get(1, 0.0)
    ratio = claim_analysis["run_length_ratio_measured_over_predicted"]
    weak_autocorrelation = abs(lag1) < 0.05
    run_length_near_independent = (ratio is not None) and (0.8 <= ratio <= 1.5)
    practical_case_falsified = weak_autocorrelation and run_length_near_independent
    return {
        "lag1_autocorrelation": lag1,
        "run_length_ratio": ratio,
        "weak_autocorrelation": weak_autocorrelation,
        "run_length_near_independent_prediction": run_length_near_independent,
        "practical_case_falsified_for_this_claim_and_operating_point": practical_case_falsified,
    }


def run_subject_investigation(subject: int, pins: dict) -> dict:
    print(f"subject {subject}: building continuous session-E stream (real pipeline, real sensors)...", flush=True)
    stream = cs.compute_signal_and_calibration_stream(subject, pins=pins)
    print(f"  {stream['n_windows']} windows over {stream['session_duration_s']:.1f}s "
          f"(hop={stream['hop_s']}s, analysis_window={stream['analysis_window_s']}s)", flush=True)

    per_claim = {}
    for claim_name, raw_values in (("Signal", stream["signal_raw"]), ("Calibration", stream["calibration_raw"])):
        per_percentile = {}
        for pct in PERCENTILES:
            analysis = _claim_temporal_analysis(raw_values, pct)
            analysis["falsification"] = falsification_verdict(analysis)
            per_percentile[pct] = analysis
        per_claim[claim_name] = per_percentile

    # Combined (verdict=Safe-equivalent) indicator at the primary (debounce) percentile,
    # using EACH claim's own percentile-derived threshold from above (not a fresh joint percentile).
    signal_restricted, _ = _restricted_indicator(stream["signal_raw"], DEBOUNCE_PERCENTILE)
    calibration_restricted, _ = _restricted_indicator(stream["calibration_raw"], DEBOUNCE_PERCENTILE)
    combined_restricted = np.logical_or(signal_restricted, calibration_restricted).astype(int).tolist()

    combined_gaps = ts.gap_lengths(combined_restricted)
    combined_runs = ts.run_lengths(combined_restricted)

    return {
        "subject": subject,
        "n_windows": stream["n_windows"],
        "session_duration_s": stream["session_duration_s"],
        "hop_s": stream["hop_s"], "analysis_window_s": stream["analysis_window_s"],
        "verified_files": stream["verified_files"],
        "per_claim": per_claim,
        "combined_indicator_at_debounce_percentile": {
            "percentile": DEBOUNCE_PERCENTILE,
            "n_restricted_windows": int(sum(combined_restricted)),
            "n_runs": len(combined_runs), "n_gaps": len(combined_gaps),
            "runs": combined_runs, "gaps": combined_gaps,
        },
    }


def step2_debounce_and_episodes(subject_result: dict) -> dict:
    """Step 2: pre-committed debounce rule applied to the COMBINED
    indicator's gaps at the primary (debounce) percentile, AND separately
    per claim (Step 4 needs each claim's own episode structure)."""
    out = {}

    combined = subject_result["combined_indicator_at_debounce_percentile"]
    combined_gaps = combined["gaps"]
    if combined_gaps:
        d_combined = ts.percentile_debounce_interval(combined_gaps, percentile=DEBOUNCE_PERCENTILE)
    else:
        d_combined = None
    out["combined"] = {"debounce_interval": d_combined, "n_gaps_available": len(combined_gaps)}

    per_claim = {}
    for claim in CLAIMS:
        analysis = subject_result["per_claim"][claim][DEBOUNCE_PERCENTILE]
        gaps = analysis["gaps"]
        restricted = analysis["restricted_indicator"]
        if gaps:
            d = ts.percentile_debounce_interval(gaps, percentile=DEBOUNCE_PERCENTILE)
            episodes = ts.merge_episodes(restricted, debounce_interval=d)
            stats = ts.episode_statistics(episodes, n_windows=analysis["n_windows"])
        else:
            d, episodes, stats = None, [], {"n_episodes": 0, "mean_episode_length": None, "mean_gap": None}
        per_claim[claim] = {"debounce_interval": d, "n_episodes": stats["n_episodes"],
                             "mean_episode_length": stats.get("mean_episode_length"),
                             "mean_gap": stats.get("mean_gap")}
    out["per_claim"] = per_claim
    return out


def step3_and_step4(subject_result: dict, debounce_result: dict) -> dict:
    rows_by_claim = {}
    for claim in CLAIMS:
        ep = debounce_result["per_claim"][claim]
        mean_ep_len, mean_gap = ep["mean_episode_length"], ep["mean_gap"]
        rows = []
        for b in SESSION_BUDGETS:
            alpha_window, fT = av.per_window_alpha(b)
            if mean_ep_len and mean_gap:
                n_onsets = av.n_onsets_per_session(mean_ep_len, mean_gap)
                alpha_episode = av.episode_alpha(b, n_onsets)
            else:
                n_onsets, alpha_episode = None, None
            rows.append({
                "session_budget": b,
                "alpha_per_window": alpha_window,
                "alpha_per_window_bp": av.alpha_to_basis_points(alpha_window),
                "per_window_representable": av.representable_at_current_granularity(alpha_window),
                "n_onsets_per_session": n_onsets,
                "alpha_episode": alpha_episode,
                "alpha_episode_bp": av.alpha_to_basis_points(alpha_episode) if alpha_episode else None,
                "episode_representable": av.representable_at_current_granularity(alpha_episode) if alpha_episode else None,
            })
        rows_by_claim[claim] = {
            "debounce_interval": ep["debounce_interval"],
            "mean_episode_length_windows": mean_ep_len,
            "mean_gap_windows": mean_gap,
            "budget_rows": rows,
        }
    return rows_by_claim


def run_mutation_checks():
    proc = subprocess.run(
        [sys.executable, "-m", "harnesses.mutation_check_event_model"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    core_proc = subprocess.run(
        [sys.executable, "-m", "harnesses.mutation_check"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    return {
        "event_model_kill_rate_line": proc.stdout.splitlines()[0] if proc.stdout else None,
        "event_model_passed": proc.returncode == 0,
        "pure_core_kill_rate_line": core_proc.stdout.splitlines()[0] if core_proc.stdout else None,
        "pure_core_unaffected": core_proc.returncode == 0,
    }


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    pins = bci_loader.load_pins()

    subject_reports = []
    for subject in SUBJECTS:
        subject_result = run_subject_investigation(subject, pins)
        debounce_result = step2_debounce_and_episodes(subject_result)
        budget_table = step3_and_step4(subject_result, debounce_result)

        for claim in CLAIMS:
            print(f"  [{claim:11s}] falsification @5%: "
                  f"{subject_result['per_claim'][claim][5.0]['falsification']['practical_case_falsified_for_this_claim_and_operating_point']}  "
                  f"lag1_autocorr={subject_result['per_claim'][claim][5.0]['falsification']['lag1_autocorrelation']:.4f}  "
                  f"run_len_ratio={subject_result['per_claim'][claim][5.0]['run_length_ratio_measured_over_predicted']}")
            print(f"                 debounce D={debounce_result['per_claim'][claim]['debounce_interval']}  "
                  f"n_episodes={debounce_result['per_claim'][claim]['n_episodes']}")

        subject_reports.append({
            "subject": subject,
            "n_windows": subject_result["n_windows"],
            "session_duration_s": subject_result["session_duration_s"],
            "verified_files": subject_result["verified_files"],
            "per_claim_temporal_summary": {
                claim: {
                    pct: {k: v for k, v in analysis.items()
                          if k not in ("restricted_indicator", "runs", "gaps")}
                    for pct, analysis in subject_result["per_claim"][claim].items()
                }
                for claim in CLAIMS
            },
            "debounce": debounce_result,
            "availability_table": budget_table,
        })

    print("\nRunning mutation checks...")
    mutation = run_mutation_checks()
    print(f"  {mutation['event_model_kill_rate_line']} (passed={mutation['event_model_passed']})")
    print(f"  pure core: {mutation['pure_core_kill_rate_line']} (unaffected={mutation['pure_core_unaffected']})")

    report = {
        "subjects": SUBJECTS, "percentiles": PERCENTILES, "debounce_percentile": DEBOUNCE_PERCENTILE,
        "session_budgets": SESSION_BUDGETS,
        "subject_reports": subject_reports,
        "mutation": mutation,
    }
    report_path = ARTIFACTS_DIR / "event_model_investigation_report.json"
    _write_json(report, report_path)

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="event_model_investigation",
        config_paths={"dataset_pins": REPO_ROOT / "config" / "dataset_pins.json"},
        params={"subjects": SUBJECTS, "percentiles": PERCENTILES, "debounce_percentile": DEBOUNCE_PERCENTILE,
                "session_budgets": SESSION_BUDGETS, "analysis_window_s": cs.DEFAULT_ANALYSIS_WINDOW_S,
                "hop_s": cs.DEFAULT_HOP_S},
        artifact_paths={"report_json": report_path},
        calibration_status="provisional",
        seeds={"note": "no stochastic seeds -- deterministic real-data sliding-window measurement"},
    )
    manifest_path = PROVENANCE_DIR / "event_model_investigation_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print(f"\nReport written to {report_path}")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
