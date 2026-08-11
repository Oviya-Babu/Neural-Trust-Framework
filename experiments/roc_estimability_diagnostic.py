"""ROC-estimability diagnostic for the Phase 9 cohort decision.

THIS IS NOT PHASE 9. Gate (verbatim from the task that authorized this
diagnostic): do NOT derive final thresholds, do NOT flip
calibration_status to 'measured', do NOT read off theta1/theta2/band_cap
values. The only question this file answers: can the held-out cohort
{subjects 4,5,6,7,8,9} alone produce statistically stable ROC estimates
for every claim, or do one or more claims require the full 9-subject pool?

EPHEMERALITY CONTRACT (the reason this file's structure looks the way it
does): "This diagnostic must not persist, cache, serialize, or display any
threshold values or operating-point parameters. If computing bootstrap
stability internally requires temporary threshold computation, those
values must remain ephemeral, must not be written to disk, logs, reports,
or artifacts, and must be discarded before the analysis completes. The
only outputs are stability metrics, confidence-band widths, and
cohort-sufficiency recommendations." This is enforced two ways, not one:
  1. Structurally: every threshold/FPR/TPR-location computation happens
     inside roc_estimability/stability.py's PRIVATE helpers
     (_low_tail_threshold, _fpr_tpr_at), whose return values are never
     propagated by any of that module's PUBLIC functions -- see its
     module docstring. This file only ever calls the public functions.
  2. Mechanically: _assert_no_forbidden_keys() below walks the final
     report dict and raises before any write to disk if a key name
     suggests a location/threshold field leaked through despite (1).

Real producer distributions, real BCIC IV 2a data, all 9 subjects (real
run of bci_pipeline.pipeline.run_subject per subject; nothing here re-runs
or modifies bci_pipeline/ or sensors/). Uses config/eis.v1.json only in
the sense that this diagnostic's whole reason for existing is the same
ppb-representable operating region eis.v1 was built for (docs/EVENT-MODEL-
INVESTIGATION.md) -- it does not load or hash the config file, since doing
so is irrelevant to a diagnostic that never derives or persists a
threshold.

Per-claim honest/attack sample construction (behaviour-level, per CLAUDE.md
section 3's attack framework -- never a directly-injected trust value):

  Signal (REAL): honest = measure_signal_quality() on each real session-E
    trial's raw epoch, unmodified. Attack = the SAME real epoch with a
    50 Hz line-noise sine injected at 3x that epoch's own per-channel std
    (a fixed, pre-committed, data-adaptive rule -- not tuned per subject).
    This is the exact behavioural attack (signal injection / line-noise
    contamination) sensors/signal_sensor.py's own docstring names as
    influencing this measurement, applied to real per-subject data instead
    of a synthetic base signal (which is all the existing unit tests use).

  Calibration (REAL): honest = measure_calibration_drift() comparing each
    subject's own real session-E features against their OWN session-T
    enrollment stats. Attack = the SAME real session-E features compared
    against a DIFFERENT subject's enrollment stats -- a genuine, real
    cross-subject session-mismatch condition (exactly the "session
    mismatch" failure sensors/calibration_sensor.py's docstring names),
    with zero synthetic injection. Foil pairing is fixed BEFORE running
    (FOIL_MAP below: subject s's foil is s+1, wrapping 9->1) -- not chosen
    per subject after seeing results.

  Model (EMULATED_PROTOCOL): honest = measure_model_integrity() against
    each subject's OWN real trained classifier artifact, correctly signed.
    Attack = the three Phase 8 attack cases (bit-flipped weights, stripped
    signature, unsigned substitute) applied to that same real artifact,
    reusing sensors/model_sensor.py directly, no new attack logic.

  Device, FSI (EMULATED_PROTOCOL): honest/attack = the real DTLS handshake
    / real swtpm quote protocol outcomes (sensors/device_sensor.py,
    sensors/fsi_sensor.py, reused directly), which do not depend on EEG
    subject identity at all. Measured once via a modest number of real
    repeats (not once per subject: real subprocess-driven protocols carry
    real wall-clock cost, and the raw_measurement they produce is a
    deterministic two-factor AND -- CEIL or FLOOR, no continuous
    variability to characterize by repeating further) and the SAME
    real-measured samples are then used for every subject's per-subject
    record. Reported honestly as subject-invariant by construction, not
    presented as if it were independent per-subject variability.

Run (needs the pipeline venv: numpy/scipy/sklearn/pyriemann/mne/moabb,
plus `openssl` and `swtpm`/`tpm2-tools` on PATH):
    .venv-pipeline/bin/python -m experiments.roc_estimability_diagnostic
"""

import json
import pathlib
import sys

import numpy as np

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bci_pipeline import pipeline as bci_pipeline_mod
from provenance import manifest as manifest_mod
from roc_estimability import stability as st
from sensors import calibration_sensor, device_certs, device_sensor, fsi_sensor, fsi_swtpm, model_sensor, signal_sensor
from trust_kernel import sign

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"

FULL_SUBJECTS = list(range(1, 10))
HELD_OUT_SUBJECTS = [4, 5, 6, 7, 8, 9]
N_BOOT = 1000
BOOTSTRAP_SEED = 20260721

# Pre-committed foil pairing for Calibration's cross-subject mismatch
# attack class -- fixed before any subject's data was inspected.
FOIL_MAP = {s: (s % 9) + 1 for s in FULL_SUBJECTS}  # 1->2, 2->3, ..., 8->9, 9->1

LINE_NOISE_FREQ_HZ = 50.0  # matches sensors/signal_sensor.py's LINE_NOISE_BAND_HZ center
LINE_NOISE_AMPLITUDE_STD_MULTIPLE = 3.0  # pre-committed, data-adaptive, not tuned per subject

MODEL_REPEATS_PER_CASE = 3
DEVICE_FSI_REPEATS_PER_CASE = 3

FORBIDDEN_KEY_SUBSTRINGS = ("threshold", "theta", "operating_point_value", "raw_measurement_at")


def _assert_no_forbidden_keys(obj, path=""):
    """Defense-in-depth: the report must never contain a key that holds a
    NUMERIC value under a threshold/operating-point-shaped name --
    structural correctness comes from roc_estimability/stability.py's
    public/private split (see module docstring); this is a second,
    independent check on the actual object about to be written. Boolean
    gate-confirmation flags (e.g. "real_roc_thresholds_derived": False) are
    deliberately exempt: their key names describe what was NOT done, and a
    bool cannot itself encode a location the way a float/int could."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            is_numeric_leak_risk = isinstance(v, (int, float)) and not isinstance(v, bool)
            key_is_suspicious = isinstance(k, str) and any(bad in k.lower() for bad in FORBIDDEN_KEY_SUBSTRINGS)
            if is_numeric_leak_risk and key_is_suspicious:
                raise RuntimeError(f"forbidden key '{k}' at {path or '<root>'} -- possible threshold/operating-point leak")
            _assert_no_forbidden_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_no_forbidden_keys(v, f"{path}[{i}]")


# --------------------------------------------------------------------------
# Signal: real per-trial honest vs. line-noise-injected attack samples.
# --------------------------------------------------------------------------

def _inject_line_noise(epoch: np.ndarray, sfreq: float) -> np.ndarray:
    n_channels, n_samples = epoch.shape
    t = np.arange(n_samples) / sfreq
    noise = np.sin(2 * np.pi * LINE_NOISE_FREQ_HZ * t)
    channel_std = epoch.std(axis=1, keepdims=True)
    return epoch + LINE_NOISE_AMPLITUDE_STD_MULTIPLE * channel_std * noise[np.newaxis, :]


def build_signal_samples(test_raw_epochs: np.ndarray, sfreq: float):
    honest, attack = [], []
    for epoch in test_raw_epochs:
        honest.append(signal_sensor.measure_signal_quality(epoch, sfreq))
        attack.append(signal_sensor.measure_signal_quality(_inject_line_noise(epoch, sfreq), sfreq))
    return honest, attack


# --------------------------------------------------------------------------
# Calibration: real own-enrollment honest vs. real cross-subject-foil attack.
# --------------------------------------------------------------------------

def build_calibration_samples(test_features: np.ndarray, own_stats: dict, foil_stats: dict):
    honest = [calibration_sensor.measure_calibration_drift(f, own_stats) for f in test_features]
    attack = [calibration_sensor.measure_calibration_drift(f, foil_stats) for f in test_features]
    return honest, attack


# --------------------------------------------------------------------------
# Model: real per-subject artifact, honest verify vs. the three Phase 8
# attack cases.
# --------------------------------------------------------------------------

def build_model_samples(clf, seed: int):
    artifact_pk, artifact_sk = sign.keypair_from_seed(seed.to_bytes(32, "big"))
    genuine_bytes = model_sensor.serialize_classifier_artifact(clf)
    signing_record = model_sensor.sign_artifact(artifact_sk, genuine_bytes)

    honest = [model_sensor.measure_model_integrity(genuine_bytes, artifact_pk, signing_record)
              for _ in range(MODEL_REPEATS_PER_CASE)]

    attack = []
    # case 1: bit-flipped weights -> hash mismatch (tamper a copy of the
    # real coefficients, never the live classifier object)
    coef_copy = np.array(clf.coef_, copy=True)
    coef_copy[0, 0] += 1e-3
    tampered_bytes = _reserialize_with_tampered_coef(clf, coef_copy)
    for _ in range(MODEL_REPEATS_PER_CASE):
        attack.append(model_sensor.measure_model_integrity(tampered_bytes, artifact_pk, signing_record))
    # case 2: stripped signature -> verify fails closed
    stripped_record = dict(signing_record)
    del stripped_record["sig"]
    for _ in range(MODEL_REPEATS_PER_CASE):
        attack.append(model_sensor.measure_model_integrity(genuine_bytes, artifact_pk, stripped_record))
    # case 3: unsigned substitute -> no signing record at all
    for _ in range(MODEL_REPEATS_PER_CASE):
        attack.append(model_sensor.measure_model_integrity(genuine_bytes, artifact_pk, None))

    return honest, attack


def _reserialize_with_tampered_coef(clf, tampered_coef):
    parts = [
        np.ascontiguousarray(tampered_coef, dtype=np.float64).tobytes(),
        np.ascontiguousarray(clf.intercept_, dtype=np.float64).tobytes(),
        np.ascontiguousarray(clf.classes_).tobytes(),
    ]
    return b"|".join(parts)


# --------------------------------------------------------------------------
# Device, FSI: subject-invariant real protocol outcomes, measured once via
# a modest number of real repeats and replicated across every subject.
# --------------------------------------------------------------------------

def build_device_samples_once():
    ca = device_certs.make_ca()
    valid = device_certs.make_valid_server_cert(ca)
    untrusted = device_certs.make_untrusted_server_cert()
    expired = device_certs.make_expired_server_cert(ca)

    honest = []
    for i in range(DEVICE_FSI_REPEATS_PER_CASE):
        result = device_sensor.run_dtls_handshake(valid["combined_pem"], ca["cert_pem"])
        guard = device_sensor.SequenceReplayGuard()
        honest.append(device_sensor.measure_device_link(result, guard.check_and_record(i + 1)))

    attack = []
    for _ in range(DEVICE_FSI_REPEATS_PER_CASE):
        result = device_sensor.run_dtls_handshake(untrusted["combined_pem"], ca["cert_pem"])
        guard = device_sensor.SequenceReplayGuard()
        attack.append(device_sensor.measure_device_link(result, guard.check_and_record(1)))
    for _ in range(DEVICE_FSI_REPEATS_PER_CASE):
        result = device_sensor.run_dtls_handshake(expired["combined_pem"], ca["cert_pem"])
        guard = device_sensor.SequenceReplayGuard()
        attack.append(device_sensor.measure_device_link(result, guard.check_and_record(1)))
    for _ in range(DEVICE_FSI_REPEATS_PER_CASE):
        result = device_sensor.run_dtls_handshake(valid["combined_pem"], ca["cert_pem"])
        guard = device_sensor.SequenceReplayGuard()
        guard.check_and_record(1)  # first presentation, accepted
        attack.append(device_sensor.measure_device_link(result, guard.check_and_record(1)))  # replay

    return honest, attack


def _nonce_hex(label: str) -> str:
    import hashlib
    return hashlib.sha256(label.encode()).hexdigest()[:40]


def build_fsi_samples_once():
    honest, attack = [], []
    with fsi_swtpm.SwtpmSession() as session:
        baseline = fsi_sensor.provision_fsi_baseline(session, b"firmware-v1-measurement")

        for i in range(DEVICE_FSI_REPEATS_PER_CASE):
            nonce = _nonce_hex(f"honest-window-{i}")
            quote = session.quote(baseline["ak_ctx"], nonce)
            result = fsi_sensor.evaluate_quote(session, baseline, quote, nonce)
            honest.append(result["raw_measurement"])

        # attack case 1: replayed quote (stale quote against a new nonce)
        for i in range(DEVICE_FSI_REPEATS_PER_CASE):
            nonce_a = _nonce_hex(f"replay-a-{i}")
            quote = session.quote(baseline["ak_ctx"], nonce_a)
            nonce_b = _nonce_hex(f"replay-b-{i}")
            result = fsi_sensor.evaluate_quote(session, baseline, quote, nonce_b)
            attack.append(result["raw_measurement"])

        # attack case 2: PCR mismatch (boot event after baseline was pinned)
        for i in range(DEVICE_FSI_REPEATS_PER_CASE):
            session.pcr_extend(f"attacker-modification-{i}".encode())
            nonce = _nonce_hex(f"pcr-mismatch-{i}")
            quote = session.quote(baseline["ak_ctx"], nonce)
            result = fsi_sensor.evaluate_quote(session, baseline, quote, nonce)
            attack.append(result["raw_measurement"])
        # attack case 3 (missing quote) is definitionally not a raw_measurement
        # sample -- CLAUDE.md 10: "a sensor that cannot measure emits
        # nothing" -- so it contributes no sample here, by design.

    return honest, attack


# --------------------------------------------------------------------------
# Per-claim analysis: class support/separation, bootstrap widths, LOSO
# swing, cohort gap, sufficiency verdict -- all via the pure, ephemerality-
# safe public API of roc_estimability/stability.py.
# --------------------------------------------------------------------------

def analyse_claim(claim_name: str, subjects_honest: dict, subjects_attack: dict, *, subject_invariant: bool):
    held_out_separating = sum(
        1 for s in HELD_OUT_SUBJECTS
        if st.class_separates(subjects_honest.get(s, []), subjects_attack.get(s, []))
    )
    held_out_present = sum(
        1 for s in HELD_OUT_SUBJECTS
        if st.class_presence(subjects_honest.get(s, []), subjects_attack.get(s, []))
    )

    held_out_widths = st.bootstrap_band_widths(
        HELD_OUT_SUBJECTS, subjects_honest, subjects_attack, n_boot=N_BOOT, seed=BOOTSTRAP_SEED)
    full_widths = st.bootstrap_band_widths(
        FULL_SUBJECTS, subjects_honest, subjects_attack, n_boot=N_BOOT, seed=BOOTSTRAP_SEED)
    loso = st.leave_one_subject_out_swing(HELD_OUT_SUBJECTS, subjects_honest, subjects_attack)
    gap = st.cohort_stability_gap(held_out_widths, full_widths)
    verdict = st.claim_sufficiency_verdict(
        n_subjects_separating=held_out_separating, bootstrap_widths=held_out_widths,
        loso_swing=loso, gap=gap,
    )

    return {
        "claim": claim_name,
        "subject_invariant_measurement": subject_invariant,
        "class_support": {
            "n_of_6_held_out_present": held_out_present,
            "n_of_6_held_out_separating": held_out_separating,
            "sufficiency_floor": st.CLASS_SUPPORT_MIN_SUBJECTS,
        },
        "bootstrap_band_widths": {"held_out_6": held_out_widths, "full_9": full_widths},
        "leave_one_subject_out_swing_held_out_6": loso,
        "cohort_stability_gap": gap,
        "sufficiency_verdict": verdict,
    }


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    print("Pass 1: running the real Phase 7 substrate for all 9 subjects "
          "(load -> filter -> artifact-detect -> Riemannian features -> LR), "
          "building Signal honest/attack samples and caching per-subject "
          "enrollment stats + test features + classifier for pass 2...")

    enrollment_stats = {}
    test_features_by_subject = {}
    signal_honest, signal_attack = {}, {}
    model_honest, model_attack = {}, {}

    for s in FULL_SUBJECTS:
        print(f"  subject {s}...")
        result = bci_pipeline_mod.run_subject(s)
        sfreq = result["test"]["arrays"]["sfreq"]

        enrollment_stats[s] = calibration_sensor.compute_enrollment_stats(result["train"]["features"])
        test_features_by_subject[s] = result["test"]["features"]

        h, a = build_signal_samples(result["test"]["arrays"]["raw_epochs"], sfreq)
        signal_honest[s], signal_attack[s] = h, a

        mh, ma = build_model_samples(result["classifier"], seed=10_000 + s)
        model_honest[s], model_attack[s] = mh, ma

        del result  # drop raw_epochs/full result; only the slim per-subject
        # pieces above are retained for pass 2

    print("Pass 2: Calibration cross-subject-foil attack samples (fixed FOIL_MAP)...")
    calibration_honest, calibration_attack = {}, {}
    for s in FULL_SUBJECTS:
        foil = FOIL_MAP[s]
        h, a = build_calibration_samples(test_features_by_subject[s], enrollment_stats[s], enrollment_stats[foil])
        calibration_honest[s], calibration_attack[s] = h, a

    print("Device: real DTLS handshakes (subject-invariant, measured once, replicated)...")
    device_h_once, device_a_once = build_device_samples_once()
    device_honest = {s: list(device_h_once) for s in FULL_SUBJECTS}
    device_attack = {s: list(device_a_once) for s in FULL_SUBJECTS}

    print("FSI: real swtpm quotes (subject-invariant, measured once, replicated)...")
    fsi_h_once, fsi_a_once = build_fsi_samples_once()
    fsi_honest = {s: list(fsi_h_once) for s in FULL_SUBJECTS}
    fsi_attack = {s: list(fsi_a_once) for s in FULL_SUBJECTS}

    print("Analysing per claim (bootstrap N=%d, subject-level resampling)..." % N_BOOT)
    claims = [
        analyse_claim("Signal", signal_honest, signal_attack, subject_invariant=False),
        analyse_claim("Calibration", calibration_honest, calibration_attack, subject_invariant=False),
        analyse_claim("Model", model_honest, model_attack, subject_invariant=False),
        analyse_claim("Device", device_honest, device_attack, subject_invariant=True),
        analyse_claim("FSI", fsi_honest, fsi_attack, subject_invariant=True),
    ]

    # ActuationFidelity has no continuously-varying real measurement in the
    # current architecture under honest, no-live-enforcement-loop operation
    # (docs/EVENT-MODEL-INVESTIGATION.md already states this scope limit for
    # streaming measurement; it applies identically here) -- reported as an
    # explicit scope note, not silently omitted.
    claims.append({
        "claim": "ActuationFidelity",
        "scope_note": (
            "No per-subject honest/attack sample construction is defined for this "
            "diagnostic: ActuationFidelity's raw_measurement (observer/observer.py) "
            "depends on a live enforcement pass comparing commanded vs. observed "
            "actuation, not on EEG subject identity or offline per-trial data -- the "
            "same scope limitation already stated in docs/EVENT-MODEL-INVESTIGATION.md "
            "section 0 for streaming measurement. Not assessed by this diagnostic; "
            "no sufficiency verdict is given for it."
        ),
    })

    recommendation = build_recommendation(claims)

    report = {
        "task": "roc_estimability_diagnostic",
        "phase_9_gate": {
            "real_roc_thresholds_derived": False,
            "calibration_status_flipped_to_measured": False,
            "theta1_theta2_band_cap_read_off": False,
        },
        "cohorts": {"held_out": HELD_OUT_SUBJECTS, "full": FULL_SUBJECTS},
        "bootstrap_n": N_BOOT,
        "pre_committed_parameters": {
            "class_support_min_subjects_of_6": st.CLASS_SUPPORT_MIN_SUBJECTS,
            "max_band_width_ratio_6_over_9": st.MAX_BAND_WIDTH_RATIO,
            "max_loso_swing_absolute": st.MAX_LOSO_SWING,
            "foil_map_calibration": FOIL_MAP,
            "line_noise_amplitude_std_multiple": LINE_NOISE_AMPLITUDE_STD_MULTIPLE,
        },
        "claims": claims,
        "recommendation": recommendation,
    }

    _assert_no_forbidden_keys(report)

    report_path = ARTIFACTS_DIR / "roc_estimability_diagnostic_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="roc_estimability_diagnostic",
        config_paths={},
        params={
            "held_out_subjects": HELD_OUT_SUBJECTS, "full_subjects": FULL_SUBJECTS,
            "bootstrap_n": N_BOOT, "bootstrap_seed": BOOTSTRAP_SEED,
        },
        artifact_paths={"report": report_path},
        calibration_status="provisional",
        seeds={"note": "model artifact-signing keys derived from fixed per-subject seeds in this file"},
    )
    manifest_path = PROVENANCE_DIR / "roc_estimability_diagnostic_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print("\n=== Per-claim results ===")
    for c in claims:
        if "scope_note" in c:
            print(f"\n{c['claim']}: SCOPE NOTE -- {c['scope_note']}")
            continue
        cs = c["class_support"]
        bw = c["bootstrap_band_widths"]
        loso = c["leave_one_subject_out_swing_held_out_6"]
        gap = c["cohort_stability_gap"]
        v = c["sufficiency_verdict"]
        print(f"\n{c['claim']} (subject_invariant_measurement={c['subject_invariant_measurement']}):")
        print(f"  class support: {cs['n_of_6_held_out_present']}/6 present, "
              f"{cs['n_of_6_held_out_separating']}/6 separating (floor={cs['sufficiency_floor']})")
        print(f"  bootstrap band width -- held_out_6: fpr={bw['held_out_6']['fpr_band_width']} "
              f"tpr={bw['held_out_6']['tpr_band_width']}")
        print(f"  bootstrap band width -- full_9:     fpr={bw['full_9']['fpr_band_width']} "
              f"tpr={bw['full_9']['tpr_band_width']}")
        print(f"  cohort stability gap (6/9 ratio): fpr={gap['fpr_band_width_ratio_6_over_9']} "
              f"tpr={gap['tpr_band_width_ratio_6_over_9']}")
        print(f"  LOSO max swing: fpr={loso['max_fpr_swing']} tpr={loso['max_tpr_swing']}")
        print(f"  sufficient_on_held_out={v['sufficient_on_held_out']} failed_tests={v['failed_tests']}")

    print("\n=== Recommendation ===")
    print(json.dumps(recommendation, indent=2))

    print(f"\nReport written to {report_path}")
    print(f"Manifest written to {manifest_path}")


def build_recommendation(claims):
    assessed = [c for c in claims if "sufficiency_verdict" in c]
    insufficient = [c for c in assessed if not c["sufficiency_verdict"]["sufficient_on_held_out"]]

    if not insufficient:
        return {
            "decision": "Option B",
            "rationale": "All assessed claims are sufficient on the held-out (4-9) cohort.",
            "claim_scoped_exceptions": [],
        }

    return {
        "decision": "claim-scoped exception",
        "rationale": (
            "One or more claims fail sufficiency on the held-out cohort; per the task's "
            "own gate, this is NOT a blanket Option A recommendation -- only the specific "
            "failing claims use the full 9-subject pool."
        ),
        "claim_scoped_exceptions": [
            {"claim": c["claim"], "failed_tests": c["sufficiency_verdict"]["failed_tests"]}
            for c in insufficient
        ],
        "claims_remaining_held_out": [
            c["claim"] for c in assessed if c["sufficiency_verdict"]["sufficient_on_held_out"]
        ],
    }


if __name__ == "__main__":
    main()
