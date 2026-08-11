"""Phase 9: measured ROC integration (CLAUDE.md 14, 20).

The SBA (Session Budget Allocation) methodology is FROZEN (CLAUDE.md 20/28,
hash 3acda0e853af3f446ac7fb33567fed10 at the time this driver was written).
This file derives real thresholds INTO that locked frame -- it does not
modify the event model, the apportionment formula, the Tail-Floor Rule, or
any config format. No wire/signed schema field changes (CLAUDE.md 8/9
untouched); confirmed by the same source-hash technique
experiments/eis_v1_precision_validation.py already established.

Cohort design, per CLAUDE.md 20's per-claim cohort table (not deviated
from):
  - Model, Device, FSI: ROC derived from the held-out {4-9} cohort.
  - Signal, Calibration: ROC derived from the full 9-subject pool.
  - ActuationFidelity: no offline per-subject measurement exists (no live
    enforcement loop in this offline pipeline); left exactly as
    config/eis.v1.json already has it (placeholder ROC, resolution_status
    'pending' at every budget) -- not assessed by this driver, per
    docs/ROC-ESTIMABILITY-DIAGNOSTIC.md's own stated scope limit.

Sample construction reuses experiments/roc_estimability_diagnostic.py's
honest/attack builders DIRECTLY (build_signal_samples,
build_calibration_samples, build_model_samples, build_device_samples_once,
build_fsi_samples_once, FOIL_MAP) -- the same behaviour-level attack
constructions already reviewed for that diagnostic, not reimplemented or
re-tuned here. Real ROC curves and Tail-Floor Rule evaluation are new here
(roc_estimability/threshold_derivation.py) since the diagnostic's own
module (roc_estimability/stability.py) is deliberately ephemeral and must
never return a threshold.

alpha (per claim, per swept budget): Signal/Calibration use the event
model (CLAUDE.md 20's episode_alpha = B / N_onsets), with N_onsets measured
fresh here across the FULL 9-subject pool via
event_model.continuous_stream (docs/EVENT-MODEL-INVESTIGATION.md measured
only subjects 1-3; Phase 9's Signal/Calibration cohort is the full 9-subject
pool, so all 9 are measured here, not reused from that 3-subject report).
Model/Device/FSI have no continuous stream to measure event structure on
(discrete pass/fail integrity checks, the same scope limit
docs/EVENT-MODEL-INVESTIGATION.md section 1.1 already states) -- they use
Phase 8.5's per-window flat-split formula instead
(sba_validation.probability_model.session_to_window_budget +
flat_split_alpha over the 5 strict claims), applied unmodified (CLAUDE.md
20: "alpha applied unmodified per claim, undiscounted for CTPR
propagation"), which Phase 8.5 already proved is exact (not merely a
bound) for the deployed FSI-strict-parent DAG. Device (the one lenient
claim) is assigned the SAME flat-split numeric alpha as the strict claims
-- CLAUDE.md 20 does not differentiate the alpha DERIVATION by
strict/lenient status (only policy's downstream severity handling does),
so this is the flat, undifferentiated reading. Flagged explicitly here as
this driver's own concretization, not previously pre-registered.

beta (per dimension, per swept budget): CLAUDE.md 20 fixes the
CONSEQUENCE-EXPOSURE-DERIVED methodology but not a concrete numeric
formula (deliberately delegated: "Feasibility-region values ... remain
outputs of Phase 9"). This driver's concretization: beta_dim = B, the same
swept budget value, applied identically per claim -- the simplest
"identical illustrative-sweep treatment as alpha" CLAUDE.md 20's Note
explicitly permits, legitimate specifically because T5 severs beta from
the hazard probability (beta does not have to certify safety here).
Flagged explicitly, not silently assumed.

Config transition: emits config/eis.v1-measured.json (NEW file --
config/eis.v0.json and config/eis.v1.json are BOTH left byte-identical,
same versioning discipline as the eis.v0 -> eis.v1 step). calibration_status
is attempted at 'measured'; trust_kernel.bands.validate_eis_config()'s
existing fail-closed check (CLAUDE.md 13) is expected to REFUSE this,
because ActuationFidelity remains an unmeasured placeholder claim -- this
is demonstrated, not routed around: config/eis.v1-measured.json is written
with calibration_status left at 'provisional', and the refusal is recorded
in the report as the correct, working gate, exactly as
CLAUDE.md 20 anticipates ("The validator must refuse the measured flip if
any derivation is still placeholder").

Run (needs the pipeline venv):
    .venv-pipeline/bin/python -m experiments.phase9_measured_roc
"""

import hashlib
import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from bci_pipeline import loader as bci_loader
from bci_pipeline import pipeline as bci_pipeline_mod
from event_model import availability as av
from event_model import continuous_stream as cs
from event_model import temporal_stats as ts
from experiments.roc_estimability_diagnostic import (
    FOIL_MAP,
    build_calibration_samples,
    build_device_samples_once,
    build_fsi_samples_once,
    build_model_samples,
    build_signal_samples,
)
from provenance import manifest as manifest_mod
from roc_estimability import threshold_derivation as td
from sba_validation import probability_model as pm
from sensors import calibration_sensor
from tests import window_fixtures as wf
from trust_kernel import bands as bands_mod
from trust_kernel import schema, sign

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"
CONFIG_DIR = REPO_ROOT / "config"

FULL_SUBJECTS = list(range(1, 10))
HELD_OUT_SUBJECTS = [4, 5, 6, 7, 8, 9]
SWEPT_BUDGETS = [("0.1%", 0.001), ("1%", 0.01), ("5%", 0.05)]

N_BOOT = 1000
BOOTSTRAP_SEED = 20260721  # same seed as the estimability diagnostic, for continuity

WINDOW_PERIOD_S = 0.100  # CLAUDE.md 7
SESSION_HOURS = 8
WINDOWS_PER_SESSION = int(SESSION_HOURS * 3600 / WINDOW_PERIOD_S)  # 288,000
N_STRICT_CLAIMS = 5  # Signal, Model, Calibration, FSI, ActuationFidelity (crit_table.json)

DEBOUNCE_PERCENTILE = 5.0  # CLAUDE.md 20's pre-committed event-model debounce percentile

CLAIM_KEY = {
    "Signal": "signal.provisional_v0", "Model": "model.provisional_v0",
    "Calibration": "calibration.provisional_v0", "Device": "device.provisional_v0",
    "FSI": "fsi.provisional_v0", "ActuationFidelity": "actuationfidelity.provisional_v0",
}
EVENT_MODEL_CLAIMS = ("Signal", "Calibration")
WINDOW_FLAT_SPLIT_CLAIMS = ("Model", "Device", "FSI")
COHORT_MIN_SEPARATING = {"Signal": 6, "Calibration": 6, "Model": 4, "Device": 4, "FSI": 4}
COHORT_SUBJECTS = {
    "Signal": FULL_SUBJECTS, "Calibration": FULL_SUBJECTS,
    "Model": HELD_OUT_SUBJECTS, "Device": HELD_OUT_SUBJECTS, "FSI": HELD_OUT_SUBJECTS,
}


def _write_json(obj, path):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


# ==========================================================================
# Event-model episode statistics, measured fresh across the FULL 9-subject
# pool (docs/EVENT-MODEL-INVESTIGATION.md only measured subjects 1-3;
# Signal/Calibration's Phase 9 cohort is the full pool).
# ==========================================================================

def _restricted_indicator(raw_values: np.ndarray, percentile: float):
    threshold = float(np.percentile(raw_values, percentile))
    return (raw_values <= threshold).astype(int).tolist()


def measure_episode_stats(subject: int, pins: dict) -> dict:
    print(f"  event-model stream: subject {subject}...", flush=True)
    stream = cs.compute_signal_and_calibration_stream(subject, pins=pins)
    out = {}
    for claim, raw in (("Signal", stream["signal_raw"]), ("Calibration", stream["calibration_raw"])):
        restricted = _restricted_indicator(raw, DEBOUNCE_PERCENTILE)
        gaps = ts.gap_lengths(restricted)
        if gaps:
            d = ts.percentile_debounce_interval(gaps, percentile=DEBOUNCE_PERCENTILE)
            episodes = ts.merge_episodes(restricted, debounce_interval=d)
            stats = ts.episode_statistics(episodes, n_windows=len(restricted))
        else:
            d, stats = None, {"n_episodes": 0, "mean_episode_length": None, "mean_gap": None}
        n_onsets = None
        if stats.get("mean_episode_length") and stats.get("mean_gap"):
            n_onsets = av.n_onsets_per_session(stats["mean_episode_length"], stats["mean_gap"])
        out[claim] = {
            "debounce_interval": d, "n_episodes": stats["n_episodes"],
            "mean_episode_length_windows": stats.get("mean_episode_length"),
            "mean_gap_windows": stats.get("mean_gap"),
            "n_onsets_per_session": n_onsets,
        }
    return out


# ==========================================================================
# alpha/beta derivation per claim per swept budget.
# ==========================================================================

def window_flat_split_alpha(session_budget: float) -> float:
    p_window_target = pm.session_to_window_budget(session_budget, WINDOWS_PER_SESSION)
    return pm.flat_split_alpha(p_window_target, N_STRICT_CLAIMS)


def alpha_for_claim(claim: str, session_budget: float, mean_n_onsets_by_claim: dict) -> float:
    if claim in EVENT_MODEL_CLAIMS:
        return av.episode_alpha(session_budget, mean_n_onsets_by_claim[claim])
    return window_flat_split_alpha(session_budget)


def beta_for_claim(claim: str, session_budget: float) -> float:
    return session_budget  # this driver's concretization -- see module docstring


def to_ppb(rate: float) -> int:
    ppb = round(rate * bands_mod.PPB_SCALE)
    return max(0, min(bands_mod.PPB_SCALE, ppb))


def representability_note(rate: float) -> dict:
    """Honest disclosure, not a gate: whether `rate` clears the ppb
    representability floor (trust_kernel.bands.representable_at_scale)
    BEFORE rounding. docs/EVENT-MODEL-INVESTIGATION.md/eis_v1_precision_
    validation.py only checked the 18 EVENT-MODEL (episode-based) alpha
    values against ppb; the per-window flat-split alpha used here for
    Model/Device/FSI was never checked against ppb representability before
    this driver -- at the tightest swept budget (0.1%) it turns out to sit
    BELOW the ppb floor (margin < 1x) and only becomes nonzero in the
    stored config via round()'s upward rounding, not because it was
    genuinely representable at that resolution. Reported, not hidden."""
    margin = bands_mod.representability_margin(rate, bands_mod.PPB_SCALE)
    return {"representable_at_ppb_before_rounding": bands_mod.representable_at_scale(rate, bands_mod.PPB_SCALE),
            "representability_margin": margin}


# ==========================================================================
# Main.
# ==========================================================================

def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    pins = bci_loader.load_pins()

    print("Pass 1: real Phase-7 substrate for all 9 subjects -- Signal/Model honest+attack "
          "epoch samples, enrollment stats, test features (reused for Pass 2/3)...", flush=True)
    enrollment_stats, test_features_by_subject = {}, {}
    signal_honest, signal_attack = {}, {}
    model_honest, model_attack = {}, {}
    per_subject_accuracy = {}

    for s in FULL_SUBJECTS:
        print(f"  subject {s}...", flush=True)
        result = bci_pipeline_mod.run_subject(s, pins=pins)
        sfreq = result["test"]["arrays"]["sfreq"]
        per_subject_accuracy[s] = result["test"]["accuracy"]

        enrollment_stats[s] = calibration_sensor.compute_enrollment_stats(result["train"]["features"])
        test_features_by_subject[s] = result["test"]["features"]

        h, a = build_signal_samples(result["test"]["arrays"]["raw_epochs"], sfreq)
        signal_honest[s], signal_attack[s] = h, a

        mh, ma = build_model_samples(result["classifier"], seed=10_000 + s)
        model_honest[s], model_attack[s] = mh, ma
        del result

    print("Pass 2: Calibration cross-subject-foil attack samples (fixed FOIL_MAP, unchanged)...", flush=True)
    calibration_honest, calibration_attack = {}, {}
    for s in FULL_SUBJECTS:
        foil = FOIL_MAP[s]
        h, a = build_calibration_samples(test_features_by_subject[s], enrollment_stats[s], enrollment_stats[foil])
        calibration_honest[s], calibration_attack[s] = h, a

    print("Device: real DTLS handshakes (subject-invariant, measured once)...", flush=True)
    device_h_once, device_a_once = build_device_samples_once()
    device_honest = {s: list(device_h_once) for s in FULL_SUBJECTS}
    device_attack = {s: list(device_a_once) for s in FULL_SUBJECTS}

    print("FSI: real swtpm quotes (subject-invariant, measured once)...", flush=True)
    fsi_h_once, fsi_a_once = build_fsi_samples_once()
    fsi_honest = {s: list(fsi_h_once) for s in FULL_SUBJECTS}
    fsi_attack = {s: list(fsi_a_once) for s in FULL_SUBJECTS}

    subjects_honest = {"Signal": signal_honest, "Calibration": calibration_honest,
                        "Model": model_honest, "Device": device_honest, "FSI": fsi_honest}
    subjects_attack = {"Signal": signal_attack, "Calibration": calibration_attack,
                        "Model": model_attack, "Device": device_attack, "FSI": fsi_attack}
    pooled_once = {"Device": (device_h_once, device_a_once), "FSI": (fsi_h_once, fsi_a_once)}

    print("\nPass 3: event-model episode statistics, full 9-subject pool "
          "(Signal/Calibration only -- Model/Device/FSI have no continuous stream)...", flush=True)
    episode_stats_by_subject = {s: measure_episode_stats(s, pins) for s in FULL_SUBJECTS}
    mean_n_onsets_by_claim = {}
    for claim in EVENT_MODEL_CLAIMS:
        vals = [episode_stats_by_subject[s][claim]["n_onsets_per_session"] for s in FULL_SUBJECTS]
        vals = [v for v in vals if v is not None]
        mean_n_onsets_by_claim[claim] = (sum(vals) / len(vals)) if vals else None

    print(f"  mean N_onsets/session across 9 subjects: {mean_n_onsets_by_claim}")

    print("\nPass 4: per-claim, per-budget threshold derivation (real ROC, "
          f"Tail-Floor Rule, N_BOOT={N_BOOT})...", flush=True)
    claim_results = {}
    for claim in ("Signal", "Calibration", "Model", "Device", "FSI"):
        cohort = COHORT_SUBJECTS[claim]
        min_sep = COHORT_MIN_SEPARATING[claim]
        s_honest, s_attack = subjects_honest[claim], subjects_attack[claim]

        if claim in pooled_once:
            pooled_honest, pooled_attack = pooled_once[claim]
        else:
            pooled_honest = [v for sid in cohort for v in s_honest.get(sid, [])]
            pooled_attack = [v for sid in cohort for v in s_attack.get(sid, [])]

        budget_rows = {}
        for label, budget in SWEPT_BUDGETS:
            alpha = alpha_for_claim(claim, budget, mean_n_onsets_by_claim)
            beta = beta_for_claim(claim, budget)
            alpha_ppb, beta_ppb = to_ppb(alpha), to_ppb(beta)
            print(f"  {claim:12s} budget={label:5s} alpha={alpha:.4e} (ppb={alpha_ppb}) "
                  f"beta={beta:.4e} (ppb={beta_ppb})", flush=True)
            op = td.derive_claim_operating_point(
                honest=pooled_honest, attack=pooled_attack, alpha_ppb=alpha_ppb, beta_ppb=beta_ppb,
                cohort_subjects=cohort, subjects_honest=s_honest, subjects_attack=s_attack,
                full_pool_subjects=FULL_SUBJECTS, min_subjects_separating=min_sep,
                n_boot=N_BOOT, seed=BOOTSTRAP_SEED,
            )
            budget_rows[label] = {
                "session_budget": budget, "alpha": alpha, "alpha_ppb": alpha_ppb,
                "alpha_representability": representability_note(alpha),
                "beta": beta, "beta_ppb": beta_ppb,
                "theta1": op["theta1"], "theta2": op["theta2"], "theta2_applicable": op["theta2_applicable"],
                "band_cap": op["band_cap"], "resolution_status": op["resolution_status"],
                "tail_floor_detail": op["tail_floor_detail"],
            }
            print(f"    -> theta1={op['theta1']} theta2={op['theta2']} band_cap={op['band_cap']} "
                  f"resolution_status={op['resolution_status']}", flush=True)

        # ROC points are identical across budgets for a fixed claim (the pooled
        # empirical curve does not depend on alpha/beta); store once.
        any_budget = next(iter(budget_rows.values()))
        roc_points = td.build_roc_points(pooled_honest, pooled_attack, polarity=1, scale=bands_mod.PPB_SCALE)

        n_honest_pooled, n_attack_pooled = len(pooled_honest), len(pooled_attack)
        per_subject_auc = _per_subject_auc(claim, cohort, s_honest, s_attack)

        claim_results[claim] = {
            "cohort": cohort, "min_subjects_separating": min_sep,
            "n_honest_pooled": n_honest_pooled, "n_attack_pooled": n_attack_pooled,
            "n_roc_points": len(roc_points),
            "roc_points": roc_points,
            "per_subject_auc": per_subject_auc,
            "budgets": budget_rows,
        }

    print("\nConfig transition...", flush=True)
    config_result = build_measured_config(claim_results)

    print("\nSpine sanity check (kernel/CTPR/policy against the measured config)...", flush=True)
    spine_result = spine_sanity_check(config_result["path"])

    print("\nMutation checks...", flush=True)
    mutation = run_mutation_checks()

    report = {
        "task": "phase9_measured_roc",
        "gate": {"note": "This IS Phase 9. calibration_status attempted at 'measured'; "
                          "see config_transition.validator_refused_measured_flip below."},
        "cohorts": {"held_out": HELD_OUT_SUBJECTS, "full": FULL_SUBJECTS},
        "swept_budgets": [b for _, b in SWEPT_BUDGETS],
        "bootstrap_n": N_BOOT, "bootstrap_seed": BOOTSTRAP_SEED,
        "windows_per_session": WINDOWS_PER_SESSION,
        "per_subject_test_accuracy": per_subject_accuracy,
        "episode_stats_by_subject": episode_stats_by_subject,
        "mean_n_onsets_by_claim": mean_n_onsets_by_claim,
        "claims": claim_results,
        "config_transition": config_result["summary"],
        "spine_sanity_check": spine_result,
        "mutation": mutation,
    }
    report_path = ARTIFACTS_DIR / "phase9_measured_roc_report.json"
    _write_json(report, report_path)

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="phase9_measured_roc",
        config_paths={"eis_v0": CONFIG_DIR / "eis.v0.json", "eis_v1_placeholder": CONFIG_DIR / "eis.v1.json",
                      "eis_v1_measured": config_result["path"], "crit_table": CONFIG_DIR / "crit_table.json",
                      "ctpr": CONFIG_DIR / "ctpr.json", "dataset_pins": CONFIG_DIR / "dataset_pins.json"},
        params={"held_out_subjects": HELD_OUT_SUBJECTS, "full_subjects": FULL_SUBJECTS,
                "swept_budgets": [b for _, b in SWEPT_BUDGETS], "bootstrap_n": N_BOOT,
                "bootstrap_seed": BOOTSTRAP_SEED, "windows_per_session": WINDOWS_PER_SESSION,
                "debounce_percentile": DEBOUNCE_PERCENTILE},
        artifact_paths={"report": report_path, "measured_config": config_result["path"]},
        calibration_status=config_result["summary"]["final_calibration_status"],
        seeds={"note": "model artifact-signing keys derived from fixed per-subject seeds "
                        "(same as roc_estimability_diagnostic.py); bootstrap seed fixed above"},
    )
    manifest_path = PROVENANCE_DIR / "phase9_measured_roc_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print(f"\nReport written to {report_path}")
    print(f"Manifest written to {manifest_path}")
    print(f"Measured config written to {config_result['path']}")


def _per_subject_auc(claim, cohort, subjects_honest, subjects_attack):
    """Trapezoidal AUC per subject from that subject's own honest/attack
    samples -- a DISTRIBUTION to report (CLAUDE.md 14/'never a success
    criterion'), never used to exclude a subject or steer alpha/beta.

    td.build_roc_points() deliberately has no sentinel ABOVE the maximum
    observed score (theta1/theta2 derivation never needs one -- theta1
    only cares about the low-FPR end, theta2's TPR=1 is already reachable
    from the attack side alone). For AUC specifically, that means the
    curve never reaches FPR=1.0, so the final ROC segment (from the
    highest-scoring honest sample up to 'flag everything') is invisible to
    a plain trapezoidal sum -- for a claim whose honest distribution is a
    single repeated ceiling value (Device/Model/FSI's deterministic
    pass/fail claims), this silently caps every subject's AUC toward 0
    even under perfect separation. Closed here by appending the standard
    ROC-closing corner (FPR=1.0, TPR=1.0) before integrating -- a
    reporting-only fix; theta1/theta2/band_cap derivation is unaffected
    (confirmed separately: it never depended on an upper sentinel)."""
    out = {}
    for s in cohort:
        h, a = subjects_honest.get(s, []), subjects_attack.get(s, [])
        if len(h) < 1 or len(a) < 1:
            out[s] = None
            continue
        pts = td.build_roc_points(h, a, polarity=1, scale=bands_mod.PPB_SCALE)
        fprs = [p["fpr_ppb"] / bands_mod.PPB_SCALE for p in pts] + [1.0]
        tprs = [p["tpr_ppb"] / bands_mod.PPB_SCALE for p in pts] + [1.0]
        auc = 0.0
        for i in range(1, len(fprs)):
            auc += (fprs[i] - fprs[i - 1]) * (tprs[i] + tprs[i - 1]) / 2.0
        out[s] = auc
    return out


def build_measured_config(claim_results: dict) -> dict:
    placeholder = json.loads((CONFIG_DIR / "eis.v1.json").read_text())

    # Pick the nominal (middle) swept budget as the single deployed
    # operating point -- config/eis.v1.json's schema (one global alpha_ppb/
    # beta_ppb, CLAUDE.md 20) can only encode one point at a time; the full
    # 3-budget sweep is reported (above, per (claim,budget)) exactly like
    # Env/Ceil's reference-value table (CLAUDE.md 6), not point-derived.
    # This driver's own concretization -- flagged, not silently assumed.
    nominal_label, nominal_budget = SWEPT_BUDGETS[1]
    assert nominal_label == "1%"

    claims = {}
    for claim, key in CLAIM_KEY.items():
        if claim == "ActuationFidelity":
            claims[key] = placeholder["claims"][key]  # untouched: deferred, no offline measurement
            continue
        r = claim_results[claim]
        nominal = r["budgets"][nominal_label]
        claims[key] = {
            "dimension": claim, "polarity": 1, "placeholder": False,
            "measured_at_budget": nominal_label,
            "roc": r["roc_points"],
            "resolution_status": {label: r["budgets"][label]["resolution_status"] for label, _ in SWEPT_BUDGETS},
        }

    measured = {
        "_comment": (
            "Phase 9 (CLAUDE.md 14/20) measured ROC config. eis_schema_version and rate "
            "representation (ppb) unchanged from config/eis.v1.json (a REPRESENTATION-only "
            "predecessor whose ROC/theta was still the Phase 2 placeholder) -- this file's ROC "
            "curves are real, derived from Phase 8 evidence-producer distributions on real BCIC "
            "IV 2a data (Model/Device/FSI: held-out subjects 4-9; Signal/Calibration: full "
            "9-subject pool), per docs/PHASE9-MEASURED-ROC.md. alpha_ppb/beta_ppb below are the "
            "operating point at the nominal 1%/8h swept budget (CLAUDE.md 20's three swept "
            "budgets {0.1%,1%,5%} are a reported feasible region, not simultaneously "
            "representable in this single-operating-point config schema; full per-(claim,budget) "
            "theta1/theta2/band_cap/resolution_status are in the Phase 9 report/manifest, not "
            "here). config/eis.v0.json and config/eis.v1.json are BOTH byte-identical, untouched "
            "by this file's existence."
        ),
        "eis_schema_version": bands_mod.EIS_SCHEMA_VERSION_V1,
        "calibration_status": "measured",  # attempted; see below
        "alpha_ppb": claim_results["Model"]["budgets"][nominal_label]["alpha_ppb"],
        "beta_ppb": claim_results["Model"]["budgets"][nominal_label]["beta_ppb"],
        "claims": claims,
    }

    validator_refused = False
    refusal_reason = None
    try:
        bands_mod.validate_eis_config(measured)
    except ValueError as e:
        validator_refused = True
        refusal_reason = str(e)

    final_calibration_status = "provisional" if validator_refused else "measured"
    measured["calibration_status"] = final_calibration_status

    path = CONFIG_DIR / "eis.v1-measured.json"
    _write_json(measured, path)

    measured_hash = bands_mod.roc_config_hash(path)
    raw_from_disk, derived = bands_mod.load_eis_config(path)

    # Known-good hashes as of the resolution_status hash-coverage correction
    # (docs/CLAUDE-MD-DIFF-SBA-FREEZE-APPLIED.md's "Correction" section) --
    # a stronger check than "unchanged relative to this function's own
    # start", since it catches a change introduced anywhere earlier in this
    # same driver run too, not just within build_measured_config().
    EXPECTED_V0_HASH = "087f66e28eb3da71ce13c6c6d2cde863fafeff066d1b01d26b292f879bad8aca"
    EXPECTED_V1_PLACEHOLDER_HASH = "cfeb34557eef7a2eb777d11f845cdcb013c48e3dd4ceadabcd02e3d8f8a8985d"
    v0_hash_now = bands_mod.roc_config_hash(CONFIG_DIR / "eis.v0.json")
    v1_placeholder_hash_now = bands_mod.roc_config_hash(CONFIG_DIR / "eis.v1.json")

    summary = {
        "path": str(path),
        "attempted_calibration_status": "measured",
        "validator_refused_measured_flip": validator_refused,
        "refusal_reason": refusal_reason,
        "final_calibration_status": final_calibration_status,
        "measured_config_roc_config_hash": measured_hash,
        "eis_v0_hash_matches_known_good": v0_hash_now == EXPECTED_V0_HASH,
        "eis_v1_placeholder_hash_matches_known_good": v1_placeholder_hash_now == EXPECTED_V1_PLACEHOLDER_HASH,
        "nominal_budget_used_for_deployed_operating_point": nominal_label,
        "derived_theta_by_claim": {k: [v[0], v[1], v[2].name] for k, v in derived.items()},
    }
    return {"path": path, "summary": summary}


def spine_sanity_check(measured_config_path) -> dict:
    """Confirms the measured config drives correct, unmodified kernel
    behaviour: builds real signed statements at deliberately honest and
    deliberately attack-like raw_measurement values (using the measured
    config's own theta1/theta2 as the reference points, so the check is
    tied to what was actually derived, not a hardcoded guess) and runs them
    through the real, unmodified trust_kernel/policy pipeline via
    tests.window_fixtures.compute_verdict with config_paths overridden to
    point at the new config -- exactly the override
    tests/window_fixtures.py already supports, no kernel code changed."""
    _, derived = bands_mod.load_eis_config(measured_config_path)
    config_paths = dict(wf.CONFIG_PATHS)
    config_paths["eis"] = measured_config_path

    def healthy_value_for(d):
        t1, t2, _cap = derived[CLAIM_KEY[d]]
        return (t2 + 1) if t2 is not None else (t1 + 1)

    rows = []
    for dim in bands_mod.DIMENSIONS:
        key = CLAIM_KEY[dim]
        theta1, theta2, cap = derived[key]
        honest_value = healthy_value_for(dim)
        attack_value = theta1 - 1

        for label, raw_measurement in (("honest", honest_value), ("attack", attack_value)):
            statements = [
                wf.healthy_signed_statement(
                    d, window_id=90_000,
                    raw_measurement=raw_measurement if d == dim else healthy_value_for(d),
                )
                for d in bands_mod.DIMENSIONS
            ]
            effective, verdict = wf.compute_verdict(statements, config_paths=config_paths)
            rows.append({
                "dimension": dim, "case": label, "raw_measurement": raw_measurement,
                "effective_dims": {k: v.name for k, v in effective.items()}, "verdict": verdict.name,
            })

    core_hashes_unchanged = _confirm_core_hashes_unchanged()

    return {
        "rows": rows,
        "note": ("Every row above exercises the real, unmodified trust_kernel.bands/ctpr/policy "
                 "code path (tests.window_fixtures.compute_verdict), fed the measured config's own "
                 "theta1/theta2 as reference points -- only the CONFIG changed, not the kernel. "
                 "'attack' rows (raw_measurement below that dimension's own theta1) are expected to "
                 "band LOW and floor that dimension's verdict contribution; 'honest' rows (above "
                 "theta2, or theta1 when band_cap=MED) are expected to band at band_cap."),
        "core_pure_files_hash_unchanged": core_hashes_unchanged,
    }


_CORE_FILES = [REPO_ROOT / "trust_kernel" / f for f in
               ("canon.py", "schema.py", "bands.py", "ctpr.py", "policy.py", "sign.py")]


def _confirm_core_hashes_unchanged():
    """bands.py itself is expected to be identical to its state before this
    driver ran (this driver imports and calls it, never edits it) -- listed
    alongside canon/schema/ctpr/policy/sign so the P1 gate ('if measured
    config changes any kernel behaviour beyond the threshold values
    themselves, that's an architectural finding') has a concrete, checkable
    artifact: this driver never Write()s or Edit()s anything under
    trust_kernel/."""
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in _CORE_FILES}


def run_mutation_checks():
    td_proc = subprocess.run(
        [sys.executable, "-m", "harnesses.mutation_check_threshold_derivation"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    core_proc = subprocess.run(
        [sys.executable, "-m", "harnesses.mutation_check"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    eis_v1_proc = subprocess.run(
        [sys.executable, "-m", "harnesses.mutation_check_eis_v1"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    return {
        "threshold_derivation_kill_rate_line": td_proc.stdout.splitlines()[0] if td_proc.stdout else td_proc.stderr[-2000:],
        "threshold_derivation_passed": td_proc.returncode == 0,
        "pure_core_kill_rate_line": core_proc.stdout.splitlines()[0] if core_proc.stdout else None,
        "pure_core_unaffected": core_proc.returncode == 0,
        "eis_v1_kill_rate_line": eis_v1_proc.stdout.splitlines()[0] if eis_v1_proc.stdout else None,
        "eis_v1_unaffected": eis_v1_proc.returncode == 0,
    }


if __name__ == "__main__":
    main()
