"""Phase 12 driver (CLAUDE.md §14: "Robustness, Fault Injection, Packaging"
-- this driver covers robustness/fault-injection; packaging is Phase F).
Real fault injection against the real kernel/enforcer/producer/log/verdict
machinery, plus honest-operation false-positive measurement and swept-budget
verdict-distribution sensitivity, at the measured config (Phase 9).

Six fault types (as specified): kernel termination, enforcer termination,
per-producer suppression (x6), verdict expiry, log corruption, log-path
exhaustion. For each: verify the specified fail-safe mode is actually
reached by real code, not asserted.

Honest scope on "kernel/enforcer termination" (stated once, here, not
re-litigated per fault): CLAUDE.md §6 is explicit that surviving a crashed/
hung/dead kernel or enforcer process is a WATCHDOG concern -- liveness only,
discharged by hardware not yet built in V1 -- and that "any claim that the
fail-safe survives enforcer compromise is false" for a live-but-malicious
enforcer. What this driver CAN and DOES verify with real code: (a) a verdict
past its own expires_at is rejected by the real enforcer, producing no
envelope; (b) no other process can write to the actuator without the exact
capability object a live enforcer holds. What it does NOT and CANNOT claim:
that the physical actuator reaches Safe on its own after either process
dies -- that is out of scope for software alone and is why CLAUDE.md §6
specifies a watchdog (liveness) and, separately, an in-path hardware ceiling
MCU as future work, not something this driver's passing result substitutes for.

Run with the pipeline venv:
    .venv-pipeline/bin/python -m experiments.phase12_fault_injection
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import json
import os
import stat
import struct
import tempfile

from bci_pipeline import loader as bci_loader
from bci_pipeline import pipeline as bci_pipeline_mod
from enforcement import clamp
from enforcement.capability import ActuatorCapability, CapabilityError, SimulatedActuator
from evidence_plane import log as evlog
from provenance import manifest as manifest_mod
from sensors import calibration_sensor, device_certs, device_sensor, fsi_sensor, fsi_swtpm, model_sensor, signal_sensor
from tests import key_fixtures as kf
from tests import window_fixtures as wf
from trust_kernel import bands as bands_mod, canon, ctpr as ctpr_mod, policy as policy_mod, schema

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"
CEIL_PATH = REPO_ROOT / "config" / "ceil.json"
ENV_PATH = REPO_ROOT / "config" / "env.json"
MEASURED_EIS_PATH = REPO_ROOT / "config" / "eis.v1-measured.json"
PHASE9_REPORT_PATH = ARTIFACTS_DIR / "phase9_measured_roc_report.json"

MEASURED_CONFIG_PATHS = {**wf.CONFIG_PATHS, "eis": MEASURED_EIS_PATH}

FP_SUBJECTS = [1, 2, 3]
SWEPT_BUDGET_LABELS = ("0.1%", "1%", "5%")

DIM_TO_CLAIM_KEY = {  # phase9_measured_roc_report.json's per-dimension key
    "Signal": "Signal", "Calibration": "Calibration", "Model": "Model",
    "Device": "Device", "FSI": "FSI",
}


# ============================================================================
# Fault 1: kernel termination (verdict staleness, honest scope per module docstring)
# ============================================================================

def fault_kernel_termination(kernel_pk):
    """The kernel stops producing fresh verdicts (crashed, killed, hung
    past its own kappa<=5ms budget many times over). The LAST real verdict
    it issued eventually crosses its own expires_at (CLAUDE.md §7's fixed
    170ms horizon). Real enforcement.accept() is what is actually tested
    here -- not a simulated timeout."""
    w = 41000
    verdict_obj = wf.issue_signed_verdict(wf.healthy_window(w, raw_measurement=100), window_id=w,
                                           issued_at=62, expires_at=170)
    still_valid = clamp.accept(verdict_obj, kernel_pk, now_ms=169, cache=clamp.AcceptCache())
    stale_after_kernel_death = clamp.accept(verdict_obj, kernel_pk, now_ms=100_000, cache=clamp.AcceptCache())

    return {
        "fault": "kernel_termination",
        "mode_verified": "no fresh verdict past expires_at is ever accepted -- enforcer produces no envelope",
        "measurements": {
            "still_within_expiry_accepted": still_valid.accepted,
            "long_after_kernel_death_accepted": stale_after_kernel_death.accepted,
            "long_after_kernel_death_reason": stale_after_kernel_death.reason,
        },
        "correct": (still_valid.accepted is True) and (stale_after_kernel_death.accepted is False),
        "scope_caveat": "Verified: the enforcer never acts on a stale verdict. NOT verified (out of scope for "
                         "software alone, CLAUDE.md §6): that the physical actuator reaches Safe on its own once "
                         "no envelope is being refreshed -- that is the watchdog/hardware-liveness mechanism's "
                         "job, not yet built in V1. This driver does not claim otherwise.",
    }


# ============================================================================
# Fault 2: enforcer termination
# ============================================================================

def fault_enforcer_termination():
    """The enforcer process dies. Modelled structurally: SimulatedActuator's
    write() checks capability `is` identity against the exact token object
    it was constructed with (enforcement/capability.py) -- a REPLACEMENT
    process (a hypothetical restarted enforcer, or an attacker) holding a
    DIFFERENT capability object cannot write, even to the same actuator
    instance. This is the real mechanism verified, not a mock."""
    cap_original = ActuatorCapability()
    actuator = SimulatedActuator(cap_original)
    actuator.write(cap_original, {"max_speed": 500, "max_acceleration": 250})  # the dead enforcer's last real write

    cap_replacement = ActuatorCapability()  # a NEW process's token -- not the one this actuator was built with
    write_blocked = False
    try:
        actuator.write(cap_replacement, {"max_speed": 1000, "max_acceleration": 500})
    except CapabilityError:
        write_blocked = True

    return {
        "fault": "enforcer_termination",
        "mode_verified": "no process other than the one holding the exact original capability object can write",
        "measurements": {
            "history_length_after_attempted_write_from_replacement": len(actuator.history),
            "replacement_write_raised_capability_error": write_blocked,
        },
        "correct": write_blocked and len(actuator.history) == 1,
        "scope_caveat": "Verified: no write succeeds without the exact live capability token. NOT verified "
                         "(same caveat as kernel_termination): that the physical actuator reaches Safe on its "
                         "own with no enforcer alive to write anything at all -- watchdog/hardware territory, "
                         "CLAUDE.md §6, not yet built.",
    }


# ============================================================================
# Fault 3: per-producer suppression (x6)
# ============================================================================

def fault_producer_suppression(config_paths=MEASURED_CONFIG_PATHS):
    """For each of the 6 dimensions in turn, the real T4 admission + reduce
    + CTPR + policy path runs with that ONE producer's statement missing
    (never substituted, never defaulted -- CLAUDE.md §10). Verifies the
    missing dimension reads LOW via absence, reports CTPR ripple when the
    suppressed producer is FSI (a CTPR parent), and reports the resulting
    verdict."""
    rows = []
    for i, suppressed in enumerate(wf.DIMENSIONS):
        w = 41100 + i
        present_statements = [wf.healthy_signed_statement(d, w, raw_measurement=100)
                               for d in wf.DIMENSIONS if d != suppressed]
        effective, verdict = wf.compute_verdict(present_statements, config_paths=config_paths)
        rows.append({
            "suppressed_dimension": suppressed,
            "suppressed_reads_low_via_absence": effective[suppressed].name == "LOW",
            "effective_dims": {k: v.name for k, v in effective.items()},
            "verdict": verdict.name,
        })
    all_correct = all(r["suppressed_reads_low_via_absence"] for r in rows)
    fsi_row = next(r for r in rows if r["suppressed_dimension"] == "FSI")
    ctpr_ripple_observed = (fsi_row["effective_dims"]["Signal"] == "LOW"
                             and fsi_row["effective_dims"]["Model"] == "LOW")
    return {
        "fault": "per_producer_suppression",
        "mode_verified": "a suppressed producer's dimension reads LOW via absence, never a default/substitute value",
        "rows": rows,
        "correct": all_correct,
        "ctpr_ripple_on_fsi_suppression_observed": ctpr_ripple_observed,
        "note": "Suppressing FSI (a CTPR parent, edges FSI->Signal/FSI->Model) drags Signal's and Model's "
                "EFFECTIVE level to LOW via meet(child, g(FSI))=meet(child, LOW)=LOW even though their own raw "
                "measurements are untouched -- the same propagation mechanism Phase 11's firmware_modification "
                "attack demonstrated, here triggered by absence rather than a failed integrity check.",
    }


# ============================================================================
# Fault 4: verdict expiry (same underlying mechanism as fault 1 / Phase 11's
# timing_attack, framed here as its own fault-injection row per the spec).
# ============================================================================

def fault_verdict_expiry(kernel_pk):
    w = 41200
    verdict_obj = wf.issue_signed_verdict(wf.healthy_window(w, raw_measurement=100), window_id=w,
                                           issued_at=62, expires_at=170)
    one_ms_before_expiry = clamp.accept(verdict_obj, kernel_pk, now_ms=169, cache=clamp.AcceptCache())
    at_expiry = clamp.accept(verdict_obj, kernel_pk, now_ms=170, cache=clamp.AcceptCache())
    one_ms_after_expiry = clamp.accept(verdict_obj, kernel_pk, now_ms=171, cache=clamp.AcceptCache())
    return {
        "fault": "verdict_expiry",
        "mode_verified": "accept(nu) requires now < expires_at strictly -- an expired verdict never produces an envelope",
        "measurements": {
            "t_minus_1ms_accepted": one_ms_before_expiry.accepted,
            "t_equals_expiry_accepted": at_expiry.accepted,
            "t_plus_1ms_accepted": one_ms_after_expiry.accepted,
        },
        "correct": one_ms_before_expiry.accepted and (not at_expiry.accepted) and (not one_ms_after_expiry.accepted),
    }


# ============================================================================
# Fault 5: log corruption
# ============================================================================

def fault_log_corruption():
    """Real EvidenceLog, real appended statements, real corruption applied
    to a decoded entry's statement content then re-written to disk as
    valid-but-tampered CBOR (exactly what an attacker editing stored bytes
    can produce: entry_hash is a public hash anyone can recompute for a
    LOCALLY self-consistent forged entry -- what they cannot do is make it
    equal the NEXT entry's already-recorded prev_hash, per
    evidence_plane/log.py's module docstring). Real read_all() + real
    verify_chain() on the re-read, tampered file.

    A raw, byte-level flip at an arbitrary offset was tried first and
    instead corrupted the CBOR encoding itself badly enough that read_all()
    raised CanonError before verify_chain() ever ran -- also a real,
    fail-loud (never fail-silent) outcome, just a coarser one than this
    function isolates; reported as an observed variant, not chased further,
    since the specific hash-chain detection property is what this fault
    needs to demonstrate precisely."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "fault5.log")
        log = evlog.EvidenceLog(path)
        for i in range(5):
            log.append(wf.healthy_signed_statement("Signal", 42000 + i, raw_measurement=50 + i))
        log.fsync_window()
        log.close()

        entries = evlog.read_all(path)
        entries[2]["statement"]["raw_measurement"] = 9999  # tamper content; entry_hash NOT recomputed

        with open(path, "wb") as f:
            for e in entries:
                record = canon.encode(e)
                f.write(struct.pack(">I", len(record)))
                f.write(record)

        reread = evlog.read_all(path)  # still valid CBOR -- decodes cleanly
        verification = evlog.verify_chain(reread)

    return {
        "fault": "log_corruption",
        "mode_verified": "a tampered entry is detected, and it plus every subsequent entry is reported broken",
        "measurements": {
            "entries_checked": verification.checked, "chain_valid": verification.valid,
            "first_broken_seq": verification.first_broken_seq, "broken_seqs": verification.broken_seqs,
        },
        "correct": (verification.valid is False) and (verification.first_broken_seq == 2)
                   and (verification.broken_seqs == [2, 3, 4]),
        "observed_variant": "A raw arbitrary-offset byte flip (tried during development) instead corrupted the "
                             "CBOR framing itself, causing read_all() to raise CanonError before verify_chain() "
                             "ran -- also fail-loud, a coarser/earlier failure than the hash-chain check this "
                             "function isolates. Both are real, observed failure modes; neither is fail-silent.",
    }


# ============================================================================
# Fault 6: log-path exhaustion
# ============================================================================

def fault_log_path_exhaustion():
    """(a) A permission-denied directory: EvidenceLog's open must fail
    LOUDLY (a real PermissionError), never silently proceed or silently
    drop writes. (b) A simulated disk-full mid-write: append() must
    propagate the real OSError from the underlying file write, never
    swallow it."""
    results = {}

    with tempfile.TemporaryDirectory() as tmp:
        locked_dir = os.path.join(tmp, "locked")
        os.makedirs(locked_dir)
        os.chmod(locked_dir, stat.S_IREAD | stat.S_IEXEC)  # read+execute only, no write
        path = os.path.join(locked_dir, "unwritable.log")
        raised_a = None
        try:
            evlog.EvidenceLog(path)
        except OSError as e:
            raised_a = type(e).__name__
        finally:
            os.chmod(locked_dir, stat.S_IRWXU)  # restore so tempdir cleanup can remove it
        results["permission_denied_directory"] = {"raised": raised_a, "fail_visible": raised_a is not None}

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "fault6b.log")
        log = evlog.EvidenceLog(path)

        class _DiskFullFile:
            def write(self, data):
                raise OSError(28, "No space left on device")  # ENOSPC

        real_file = log._file
        log._file = _DiskFullFile()
        raised_b = None
        try:
            log.append(wf.healthy_signed_statement("Signal", 43000, raw_measurement=50))
        except OSError as e:
            raised_b = f"{type(e).__name__}: {e}"
        finally:
            log._file = real_file
            log.close()
        results["disk_full_mid_write"] = {"raised": raised_b, "fail_visible": raised_b is not None}

    return {
        "fault": "log_path_exhaustion",
        "mode_verified": "a log that cannot be opened or written fails LOUDLY (real exception propagates), never silently",
        "measurements": results,
        "correct": results["permission_denied_directory"]["fail_visible"] and results["disk_full_mid_write"]["fail_visible"],
    }


# ============================================================================
# Honest-operation false-positive rate + swept-budget verdict-distribution
# sensitivity, at real subject data.
# ============================================================================

def _honest_producer_context():
    """Session-level real honest evidence that does not vary per trial
    (Model/Device/FSI are protocol-level and subject-invariant by
    construction, CLAUDE.md §20 -- one real check suffices, reused, exactly
    matching how these producers are actually specified to run: 'checked
    once per session... re-announced each window')."""
    artifact_seed = __import__("hashlib").sha256(b"phase12-fp-rate-model-artifact-seed").digest()
    from trust_kernel import sign
    artifact_pk, artifact_sk = sign.keypair_from_seed(artifact_seed)

    pins = bci_loader.load_pins()
    result1 = bci_pipeline_mod.run_subject(1, pins=pins)
    artifact_bytes = model_sensor.serialize_classifier_artifact(result1["classifier"])
    signing_record = model_sensor.sign_artifact(artifact_sk, artifact_bytes)

    ca = device_certs.make_ca()
    valid_cert = device_certs.make_valid_server_cert(ca)
    handshake = device_sensor.run_dtls_handshake(valid_cert["combined_pem"], ca["cert_pem"])

    return {"artifact_bytes": artifact_bytes, "artifact_pk": artifact_pk, "signing_record": signing_record,
            "handshake": handshake, "pins": pins}


def _build_honest_window(ctx, fsi_eval, w, raw_epoch, sfreq, feature_vector, enrollment_stats, producers):
    signal_stmt = producers["signal"].build_statement(raw_epoch=raw_epoch, sfreq=sfreq, window_id=w, claimed_at=0)
    calib_stmt = producers["calibration"].build_statement(feature_vector=feature_vector, enrollment_stats=enrollment_stats,
                                                            window_id=w, claimed_at=0)
    model_stmt = producers["model"].build_statement(artifact_bytes=ctx["artifact_bytes"], artifact_public_key=ctx["artifact_pk"],
                                                      signing_record=ctx["signing_record"], window_id=w, claimed_at=0)
    device_stmt = producers["device"].build_statement(handshake_result=ctx["handshake"], sequence_number=w, window_id=w, claimed_at=0)
    fsi_stmt = producers["fsi"].build_statement(evaluation=fsi_eval, window_id=w, claimed_at=0)
    af_stmt = wf.healthy_signed_statement("ActuationFidelity", w, raw_measurement=100)  # commanded==observed, honest
    return [signal_stmt, calib_stmt, model_stmt, device_stmt, fsi_stmt, af_stmt]


def _eis_derived_for_budget(budget_label, measured_config_derived):
    """Per-claim (theta1, theta2, band_cap) at one swept budget, sourced
    directly from Phase 9's ALREADY-DERIVED, authoritative per-(claim,
    budget) values in artifacts/phase9_measured_roc_report.json -- never
    re-derived, never recomputed. ActuationFidelity has no swept derivation
    (no offline measurement path, resolution_status=pending); it keeps the
    same placeholder-derived value the shipped measured config already
    uses, at every budget, per that documented limitation."""
    phase9 = json.loads(PHASE9_REPORT_PATH.read_text())
    derived = {}
    for dim, key in DIM_TO_CLAIM_KEY.items():
        b = phase9["claims"][key]["budgets"][budget_label]
        claim_type = wf.CLAIM_TYPE_BY_DIM[dim]
        derived[claim_type] = (b["theta1"], b["theta2"], bands_mod.TrustLevel[b["band_cap"]])
    af_claim_type = wf.CLAIM_TYPE_BY_DIM["ActuationFidelity"]
    derived[af_claim_type] = measured_config_derived[af_claim_type]
    return derived


def _verdict_from_derived(statements, eis_derived, edges, strict, lenient, claim_registry):
    by_dimension = {d: [] for d in wf.DIMENSIONS}
    for stmt in statements:
        claim_entry = claim_registry["claims"][stmt["claim_type"]]
        theta1, theta2, cap = eis_derived[stmt["claim_type"]]
        s = bands_mod.score(1, stmt["raw_measurement"])
        by_dimension[claim_entry["dimension"]].append(bands_mod.band(s, theta1, theta2, cap))
    raw_dims = {d: bands_mod.reduce_dimension(c) if c else bands_mod.reduce_dimension([None])
                for d, c in by_dimension.items()}
    effective = ctpr_mod.apply_ctpr(raw_dims, edges)
    verdict = policy_mod.policy(effective, strict, lenient)
    return effective, verdict


def honest_operation_analysis():
    """Runs many REAL honest trials (real Signal/Calibration measurements
    per trial, real session-level Model/Device/FSI checks) through the
    full real pipeline at (a) the shipped measured config, and (b) each of
    the three swept-budget threshold sets, and tabulates the verdict
    distribution -- the false-positive-like rate under 100% honest
    operation, and its sensitivity to the swept budget."""
    ctx = _honest_producer_context()
    producers = {
        "signal": signal_sensor.SignalSensor(kf.keypair_for(signal_sensor.SIGNAL_SOURCE_ID)[1]),
        "calibration": calibration_sensor.CalibrationSensor(kf.keypair_for(calibration_sensor.CALIBRATION_SOURCE_ID)[1]),
        "model": model_sensor.ModelSensor(kf.keypair_for(model_sensor.MODEL_SOURCE_ID)[1]),
        "device": device_sensor.DeviceSensor(kf.keypair_for(device_sensor.DEVICE_SOURCE_ID)[1]),
        "fsi": fsi_sensor.FsiSensor(kf.keypair_for(fsi_sensor.FSI_SOURCE_ID)[1]),
    }

    _, measured_derived = bands_mod.load_eis_config(MEASURED_EIS_PATH)
    _, edges = ctpr_mod.load_ctpr_config(wf.CONFIG_PATHS["ctpr"])
    _, strict, lenient = policy_mod.load_crit_table(wf.CONFIG_PATHS["crit_table"])
    claim_registry = schema.load_claim_registry(wf.CONFIG_PATHS["claim_registry"])
    budget_derived = {b: _eis_derived_for_budget(b, measured_derived) for b in SWEPT_BUDGET_LABELS}

    all_windows = []
    with fsi_swtpm.SwtpmSession() as fsi_session:
        fsi_baseline = fsi_sensor.provision_fsi_baseline(fsi_session, ctx["artifact_bytes"])
        nonce = __import__("hashlib").sha256(b"phase12-fp-rate-honest-quote").hexdigest()[:40]
        quote = fsi_session.quote(fsi_baseline["ak_ctx"], nonce)
        fsi_eval = fsi_sensor.evaluate_quote(fsi_session, fsi_baseline, quote, nonce)

        w = 44000
        for subject in FP_SUBJECTS:
            result = bci_pipeline_mod.run_subject(subject, pins=ctx["pins"])
            train, test = result["train"], result["test"]
            enrollment_stats = calibration_sensor.compute_enrollment_stats(train["features"])
            sfreq = train["arrays"]["sfreq"]
            for i in range(test["arrays"]["raw_epochs"].shape[0]):
                statements = _build_honest_window(
                    ctx, fsi_eval, w, test["arrays"]["raw_epochs"][i], sfreq, test["features"][i],
                    enrollment_stats, producers,
                )
                all_windows.append({"subject": subject, "window_id": w, "statements": statements})
                w += 1

    def distribution(eis_derived):
        counts = {"Safe": 0, "Constrained": 0, "Normal": 0}
        for rec in all_windows:
            _, verdict = _verdict_from_derived(rec["statements"], eis_derived, edges, strict, lenient, claim_registry)
            counts[verdict.name] += 1
        n = len(all_windows)
        return {"counts": counts, "n": n,
                "fraction_not_normal": (n - counts["Normal"]) / n,
                "fraction_safe": counts["Safe"] / n, "fraction_constrained": counts["Constrained"] / n,
                "fraction_normal": counts["Normal"] / n}

    measured_dist = distribution(measured_derived)
    per_budget_dist = {b: distribution(budget_derived[b]) for b in SWEPT_BUDGET_LABELS}

    return {
        "n_honest_windows": len(all_windows), "subjects": FP_SUBJECTS,
        "shipped_measured_config": {"path": str(MEASURED_EIS_PATH.relative_to(REPO_ROOT)), "distribution": measured_dist},
        "swept_budget_sensitivity": per_budget_dist,
        "note": "fraction_not_normal under 100% HONEST operation is the false-positive-like rate at the measured "
                "thresholds -- every window here is real, unmanipulated evidence (CLAUDE.md 3's Behaviour-Based "
                "Attack Framework: no trust injected). Per-budget distributions use Phase 9's ALREADY-DERIVED "
                "theta1/theta2/band_cap per (claim, budget), re-cited from artifacts/phase9_measured_roc_report.json, "
                "never re-derived here.",
    }


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    kernel_pk = wf.kernel_public_key()

    print("Fault 1/6: kernel_termination ...")
    f1 = fault_kernel_termination(kernel_pk)
    print("Fault 2/6: enforcer_termination ...")
    f2 = fault_enforcer_termination()
    print("Fault 3/6: per_producer_suppression ...")
    f3 = fault_producer_suppression()
    print("Fault 4/6: verdict_expiry ...")
    f4 = fault_verdict_expiry(kernel_pk)
    print("Fault 5/6: log_corruption ...")
    f5 = fault_log_corruption()
    print("Fault 6/6: log_path_exhaustion ...")
    f6 = fault_log_path_exhaustion()

    faults = [f1, f2, f3, f4, f5, f6]
    for f in faults:
        print(f"  {f['fault']:30s} correct={f['correct']}")

    print("\nHonest-operation false-positive rate + swept-budget sensitivity "
          f"(subjects {FP_SUBJECTS}, real pipeline, real data) ...")
    honest = honest_operation_analysis()
    print(f"  n_honest_windows={honest['n_honest_windows']}")
    print(f"  shipped measured config: {honest['shipped_measured_config']['distribution']}")
    for b in SWEPT_BUDGET_LABELS:
        print(f"  budget {b}: {honest['swept_budget_sensitivity'][b]}")

    report = {"faults": faults, "all_faults_correct": all(f["correct"] for f in faults), "honest_operation": honest}
    report_path = ARTIFACTS_DIR / "phase12_fault_injection_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT, experiment_name="phase12_fault_injection",
        config_paths={"crit_table": wf.CONFIG_PATHS["crit_table"], "ctpr": wf.CONFIG_PATHS["ctpr"],
                      "eis_v1_measured": MEASURED_EIS_PATH, "key_registry": wf.CONFIG_PATHS["key_registry"],
                      "claim_registry": wf.CONFIG_PATHS["claim_registry"], "ceil": CEIL_PATH, "env": ENV_PATH,
                      "dataset_pins": REPO_ROOT / "config" / "dataset_pins.json"},
        params={"fp_subjects": FP_SUBJECTS, "n_honest_windows": honest["n_honest_windows"]},
        artifact_paths={"report_json": report_path, "phase9_source": PHASE9_REPORT_PATH},
        calibration_status="provisional",
        seeds={"note": "sensor/kernel/artifact-publisher keys from named seeds; single real honest FSI quote and "
                        "DTLS handshake reused across all windows (session-level, subject-invariant by construction, "
                        "CLAUDE.md 20); swept-budget theta1/theta2/band_cap re-cited from Phase 9's artifact, not re-derived"},
    )
    manifest_path = PROVENANCE_DIR / "phase12_fault_injection_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print(f"\nAll faults correct: {report['all_faults_correct']}")
    print(f"Report written to {report_path}")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
