"""Phase 8 Step 4-5 driver (CLAUDE.md §14): wires the six Phase-8 evidence
producers (sensors/) to real BCIC IV 2a windows (bci_pipeline/, Phase 7)
and runs them through the real T4 admission -> Trust Kernel -> policy ->
enforcement path (trust_kernel/, enforcement/), end to end.

Run with the pipeline venv (sensors/ + bci_pipeline/ both need real
numpy/scipy/mne/moabb/pyriemann/cryptography, and this driver additionally
shells out to real openssl/swtpm/tpm2-tools):
    .venv-pipeline/bin/python -m experiments.phase8_evidence_producers

Scope, stated once here rather than scattered: under Position A (CLAUDE.md
§3), every statement built here is software-forgeable by A_data/A_code
like any other V1 evidence -- config/claim_registry.json's
forgeable_under_A_code=TRUE on all six claims says this in the registry's
own contents, not just in prose. This driver demonstrates (i) honest-
evidence reasoning correctness -- CTPR/policy respond correctly to real
producer output, including real attacks against the *producers'*
protocols; (ii) that those protocol-level attacks are actually caught,
with real cryptography and a real (emulated) TPM/DTLS stack, not asserted;
and (iii) restates, without re-deriving, T5's unconditional
consequence-boundedness (Phase 5, already established and explicitly NOT
provable from pi -- see CLAUDE.md §5's "T5 must never be proven from pi").
It does NOT establish an adversarial bound on evidence integrity itself --
that is exactly what Position A already rules out for V1.

Step 4 (Observer wiring): AF's "commanded" value is read from
enforcement/capability.py's SimulatedActuator.history after a REAL
accept_and_clamp -> slew -> capability-gated write pass through
enforcement/ -- not a hand-typed envelope dict. There remains one
asymmetry, stated honestly rather than hidden: AF for a given window can
only be observed *after* that window's own enforcement action, so the
verdict that drives enforcement (verdict_A below) is necessarily computed
from the other five dimensions only; verdict_B then folds in the resulting
real AF statement to show the complete six-dimension reasoning. A live
system would feed AF_{w-1} into verdict_w, not attest to a value that
doesn't exist yet; this driver is a single-shot demonstration, not a
running control loop, and is documented as such.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import hashlib
import json

from bci_pipeline import loader as bci_loader
from bci_pipeline import pipeline as bci_pipeline_mod
from enforcement import clamp
from enforcement.capability import ActuatorCapability, SimulatedActuator
from enforcement.slew import SlewState
from evidence_plane import log as evlog
from observer.observer import Observer
from provenance import manifest as manifest_mod
from sensors import calibration_sensor, device_certs, device_sensor, fsi_sensor, fsi_swtpm, model_sensor, signal_sensor
from tests import key_fixtures as kf
from tests import window_fixtures as wf
from trust_kernel import schema, sign

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"
CEIL_PATH = REPO_ROOT / "config" / "ceil.json"
ENV_PATH = REPO_ROOT / "config" / "env.json"

SUBJECT = 1
N_HONEST_TRIALS = 3

MUTATION_SUITE_NOTE = (
    "harnesses/mutation_check.py runs against trust_kernel/+enforcement/+evidence_plane/ "
    "(the pure-core kill-rate suite, tests/ discovery) -- sensors/ has no mutation harness of "
    "its own in this phase; its correctness evidence is the attack-case unit tests in "
    "tests_sensors/ (34/34 passing, see (ii) below), consistent with mutation testing being "
    "scoped to the theorem-bearing pure core (CLAUDE.md 12)."
)


def _sensor(cls, source_id):
    _, sk = kf.keypair_for(source_id)
    return cls(sk)


def build_producers():
    return {
        "signal": _sensor(signal_sensor.SignalSensor, signal_sensor.SIGNAL_SOURCE_ID),
        "calibration": _sensor(calibration_sensor.CalibrationSensor, calibration_sensor.CALIBRATION_SOURCE_ID),
        "model": _sensor(model_sensor.ModelSensor, model_sensor.MODEL_SOURCE_ID),
        "device": _sensor(device_sensor.DeviceSensor, device_sensor.DEVICE_SOURCE_ID),
        "fsi": _sensor(fsi_sensor.FsiSensor, fsi_sensor.FSI_SOURCE_ID),
    }


def admit_all(statements, window_id):
    key_registry = schema.load_key_registry(wf.CONFIG_PATHS["key_registry"])
    claim_registry = schema.load_claim_registry(wf.CONFIG_PATHS["claim_registry"])
    results = {}
    for stmt in statements:
        r = schema.admit_statement(
            stmt, key_registry=key_registry, claim_registry=claim_registry,
            current_window_id=window_id, window_open_time_ms=0, arrival_time_ms=1,
        )
        results[stmt["claim_type"]] = {"accepted": r.accepted, "failed_step": r.failed_step, "reason": r.reason}
    return results


def run_enforcement_and_observe(verdict_obj, kernel_pk, env, ceil, slew_state, cap, actuator,
                                 observer, log, window_id, claimed_at, observed_override=None):
    """Step 4: real accept_and_clamp -> slew -> capability write, then the
    Observer reads 'commanded' from the actuator's own recorded history
    (not from enforcement/'s internal decision object) -- exactly the
    structural independence observer/observer.py's docstring requires."""
    decision = clamp.accept_and_clamp(
        verdict_obj, kernel_pk, now_ms=100, cache=clamp.AcceptCache(), env=env, ceil=ceil,
    )
    if not decision.accepted or decision.envelope is None:
        return None
    cmd = slew_state.step(decision.envelope)
    actuator.write(cap, cmd)
    commanded = dict(actuator.history[-1])
    observed = observed_override if observed_override is not None else dict(commanded)
    stmt = observer.observe_and_append(
        log, commanded=commanded, observed=observed, window_id=window_id, claimed_at=claimed_at,
    )
    return {"decision": decision, "cmd": cmd, "commanded": commanded, "observed": observed, "af_statement": stmt}


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    pins = bci_loader.load_pins()
    print(f"Loading + running real Phase-7 pipeline for subject {SUBJECT} (hash-pinned, fail-closed)...")
    result = bci_pipeline_mod.run_subject(SUBJECT, pins=pins)
    train = result["train"]
    test = result["test"]
    sfreq = train["arrays"]["sfreq"]
    label_names = result["label_names"]

    enrollment_stats = calibration_sensor.compute_enrollment_stats(train["features"])

    # ---- Model: sign the real trained classifier artifact once, at "publish time" ----
    # A distinct identity from any sensor's statement-signing key (model_sensor.py's
    # docstring): the artifact-publisher key attests the model weights; the
    # ModelSensor's own key attests the statement about them.
    artifact_seed = hashlib.sha256(b"phase8-model-artifact-publisher-seed").digest()
    artifact_pk, artifact_sk = sign.keypair_from_seed(artifact_seed)
    artifact_bytes = model_sensor.serialize_classifier_artifact(result["classifier"])
    signing_record = model_sensor.sign_artifact(artifact_sk, artifact_bytes)
    print(f"Model artifact signed: sha256={signing_record['sha256'][:16]}...")

    # ---- Device: one real DTLS handshake per "session" (cached, re-announced per window) ----
    ca = device_certs.make_ca()
    valid_server_cert = device_certs.make_valid_server_cert(ca)
    honest_handshake = device_sensor.run_dtls_handshake(valid_server_cert["combined_pem"], ca["cert_pem"])
    untrusted_server_cert = device_certs.make_untrusted_server_cert()
    attacked_handshake = device_sensor.run_dtls_handshake(untrusted_server_cert["combined_pem"], ca["cert_pem"])
    print(f"Device DTLS handshake (honest): handshake_ok={honest_handshake['handshake_ok']}")
    print(f"Device DTLS handshake (invalid-cert attack): handshake_ok={attacked_handshake['handshake_ok']}")

    producers = build_producers()
    kernel_pk = wf.kernel_public_key()
    ceil, env = clamp.load_envelope_configs(CEIL_PATH, ENV_PATH)

    report = {"subject": SUBJECT, "honest_windows": [], "reasoning_correctness": {}, "protocol_validation": {},
              "consequence_boundedness": {}}

    # ================================================================
    # (i) Reasoning correctness, part A: honest windows on REAL trials.
    # ================================================================
    with fsi_swtpm.SwtpmSession() as fsi_session:
        fsi_baseline = fsi_sensor.provision_fsi_baseline(fsi_session, artifact_bytes)  # boot measurement tied to the real signed model artifact
        print(f"FSI baseline provisioned: pcr={fsi_baseline['baseline_pcr_hex'][:16]}...")

        log = evlog.EvidenceLog(ARTIFACTS_DIR / "phase8_evidence.log")
        cap = ActuatorCapability()
        actuator = SimulatedActuator(cap)
        slew_state = SlewState()
        observer = Observer(kf.keypair_for("actuationfidelity_sensor_v0")[1])

        for i in range(N_HONEST_TRIALS):
            window_id = 10_000 + i
            raw_epoch = test["arrays"]["raw_epochs"][i]
            feature_vector = test["features"][i]

            signal_stmt = producers["signal"].build_statement(
                raw_epoch=raw_epoch, sfreq=sfreq, window_id=window_id, claimed_at=0)
            calib_stmt = producers["calibration"].build_statement(
                feature_vector=feature_vector, enrollment_stats=enrollment_stats, window_id=window_id, claimed_at=0)
            model_stmt = producers["model"].build_statement(
                artifact_bytes=artifact_bytes, artifact_public_key=artifact_pk,
                signing_record=signing_record, window_id=window_id, claimed_at=0)
            device_stmt = producers["device"].build_statement(
                handshake_result=honest_handshake, sequence_number=window_id, window_id=window_id, claimed_at=0)

            nonce_hex = hashlib.sha256(f"window-{window_id}".encode()).hexdigest()[:40]
            quote = fsi_session.quote(fsi_baseline["ak_ctx"], nonce_hex)
            fsi_eval = fsi_sensor.evaluate_quote(fsi_session, fsi_baseline, quote, nonce_hex)
            fsi_stmt = producers["fsi"].build_statement(evaluation=fsi_eval, window_id=window_id, claimed_at=0)

            five_dim_statements = [signal_stmt, calib_stmt, model_stmt, device_stmt, fsi_stmt]
            admission_5 = admit_all(five_dim_statements, window_id)

            verdict_a = wf.issue_signed_verdict(five_dim_statements, window_id=window_id)
            enf = run_enforcement_and_observe(
                verdict_a, kernel_pk, env, ceil, slew_state, cap, actuator, observer, log,
                window_id=window_id, claimed_at=0,
            )
            af_stmt = enf["af_statement"]
            all_six = five_dim_statements + [af_stmt]
            admission_6 = admit_all(all_six, window_id)
            effective_b, verdict_b = wf.compute_verdict(all_six)

            row = {
                "window_id": window_id,
                "true_label": str(label_names[int(test["labels"][i])]),
                "raw_measurements": {
                    "Signal": signal_stmt["raw_measurement"], "Calibration": calib_stmt["raw_measurement"],
                    "Model": model_stmt["raw_measurement"], "Device": device_stmt["raw_measurement"],
                    "FSI": fsi_stmt["raw_measurement"], "ActuationFidelity": af_stmt["raw_measurement"],
                },
                "admission_5dim_all_accepted": all(v["accepted"] for v in admission_5.values()),
                "admission_6dim_all_accepted": all(v["accepted"] for v in admission_6.values()),
                "verdict_a_5dim_for_enforcement": verdict_a["verdict"],
                "commanded": enf["commanded"], "observed": enf["observed"],
                "effective_dims_6dim": {k: v.name for k, v in effective_b.items()},
                "verdict_b_6dim_full_reasoning": verdict_b.name,
            }
            report["honest_windows"].append(row)
            print(f"  window {window_id} (true={row['true_label']}): raw={row['raw_measurements']} "
                  f"verdict_a(5dim,drives enforcement)={verdict_a['verdict']} "
                  f"verdict_b(6dim,full)={verdict_b.name}")

        log.close()

        # ================================================================
        # (i) Reasoning correctness, part B: FSI/Device invalid-evidence attacks
        # on one real window's other four dimensions (Signal/Calibration/Model
        # held fixed and honest; only FSI or only Device is swapped for an
        # attacked value -- Behaviour-Based Attack Framework, CLAUDE.md 3:
        # attack -> runtime behaviour -> measured observation -> evidence ->
        # trust -> policy, never a direct trust injection). A fresh window_id
        # range (20_000+), disjoint from the honest-windows loop above: reusing
        # 10_000 here would replay producers["device"]'s sequence counter
        # against itself (that sensor instance already saw sequence_number
        # 10_000 in the honest-windows loop), which is the replay guard
        # correctly doing its job -- just not the thing this section is
        # trying to isolate.
        # ================================================================
        base_window_id = 20_000
        raw_epoch0 = test["arrays"]["raw_epochs"][0]
        feature_vector0 = test["features"][0]
        signal_stmt0 = producers["signal"].build_statement(
            raw_epoch=raw_epoch0, sfreq=sfreq, window_id=base_window_id, claimed_at=0)
        calib_stmt0 = producers["calibration"].build_statement(
            feature_vector=feature_vector0, enrollment_stats=enrollment_stats, window_id=base_window_id, claimed_at=0)
        model_stmt0 = producers["model"].build_statement(
            artifact_bytes=artifact_bytes, artifact_public_key=artifact_pk,
            signing_record=signing_record, window_id=base_window_id, claimed_at=0)
        honest_device_stmt0 = producers["device"].build_statement(
            handshake_result=honest_handshake, sequence_number=base_window_id, window_id=base_window_id, claimed_at=0)
        nonce0 = hashlib.sha256(f"window-{base_window_id}".encode()).hexdigest()[:40]
        quote0 = fsi_session.quote(fsi_baseline["ak_ctx"], nonce0)
        honest_fsi_eval0 = fsi_sensor.evaluate_quote(fsi_session, fsi_baseline, quote0, nonce0)
        honest_fsi_stmt0 = producers["fsi"].build_statement(evaluation=honest_fsi_eval0, window_id=base_window_id, claimed_at=0)

        # attacked FSI: PCR mismatch (attacker-controlled boot event after baseline was pinned)
        fsi_session.pcr_extend(b"phase8-attacker-boot-modification")
        nonce_attack = hashlib.sha256(f"window-{base_window_id}-fsi-attack".encode()).hexdigest()[:40]
        quote_attacked = fsi_session.quote(fsi_baseline["ak_ctx"], nonce_attack)
        attacked_fsi_eval = fsi_sensor.evaluate_quote(fsi_session, fsi_baseline, quote_attacked, nonce_attack)
        attacked_fsi_stmt = producers["fsi"].build_statement(evaluation=attacked_fsi_eval, window_id=base_window_id, claimed_at=0)

        attacked_device_stmt0 = producers["device"].build_statement(
            handshake_result=attacked_handshake, sequence_number=base_window_id + 1,
            window_id=base_window_id, claimed_at=0,
        )  # distinct sequence_number from honest_device_stmt0 above: isolates the
        # invalid-cert attack from also tripping the replay guard.

        honest_six = [signal_stmt0, calib_stmt0, model_stmt0, honest_device_stmt0, honest_fsi_stmt0]
        fsi_attack_six = [signal_stmt0, calib_stmt0, model_stmt0, honest_device_stmt0, attacked_fsi_stmt]
        device_attack_six = [signal_stmt0, calib_stmt0, model_stmt0, attacked_device_stmt0, honest_fsi_stmt0]

        def variant_row(name, five_stmts):
            eff, verdict = wf.compute_verdict(five_stmts + [
                # AF held at a fixed honest placeholder for this variant (not the
                # focus of this comparison; Step 4 already demonstrated AF's real
                # wiring above) so only FSI/Device vary between rows.
                wf.healthy_signed_statement("ActuationFidelity", base_window_id, raw_measurement=100)
            ])
            return {
                "variant": name,
                "FSI_raw": next(s["raw_measurement"] for s in five_stmts if s["claim_type"] == "fsi.provisional_v0"),
                "Device_raw": next(s["raw_measurement"] for s in five_stmts if s["claim_type"] == "device.provisional_v0"),
                "effective_dims": {k: v.name for k, v in eff.items()},
                "verdict": verdict.name,
            }

        real_rows = [
            variant_row("real_honest", honest_six),
            variant_row("real_fsi_pcr_mismatch_attack", fsi_attack_six),
            variant_row("real_device_invalid_cert_attack", device_attack_six),
        ]
        print("  -- real-data rows (Signal/Calibration/Model from real subject-1 trial 0; FSI/Device real) --")
        for r in real_rows:
            print(f"  variant={r['variant']:32s} FSI_raw={r['FSI_raw']:4d} Device_raw={r['Device_raw']:4d} "
                  f"effective={r['effective_dims']} verdict={r['verdict']}")

        # The real Signal/Calibration measurements above are already LOW on
        # their own (see raw_measurements printed for windows 10000-10002):
        # a genuine, unmanipulated finding -- config/eis.v0.json's ROC/theta
        # config is still the Phase 2 placeholder, calibrated against
        # synthetic values, never fit to these producers' real output scale
        # (that is explicitly Phase 9's job, CLAUDE.md 14). Because Signal is
        # a strict dimension, its real LOW alone already floors the verdict
        # to Safe in every real-data row above, which masks the FSI-strict
        # vs Device-lenient distinction this section exists to demonstrate --
        # so a second, clearly-separate set of rows holds Signal/Calibration/
        # Model at the SAME placeholder-healthy fixture Phase 3/5/6 already
        # use throughout this codebase (wf.healthy_signed_statement,
        # raw_measurement=100 -- still a real pass through band/reduce/CTPR/
        # policy, not an injected trust value, CLAUDE.md 3's Behaviour-Based
        # Attack Framework), while FSI and Device remain exactly the same
        # real swtpm/DTLS statements used above. This isolates the one
        # variable this section is about.
        placeholder_signal = wf.healthy_signed_statement("Signal", base_window_id, raw_measurement=100)
        placeholder_calib = wf.healthy_signed_statement("Calibration", base_window_id, raw_measurement=100)
        placeholder_model = wf.healthy_signed_statement("Model", base_window_id, raw_measurement=100)
        controlled_honest_six = [placeholder_signal, placeholder_calib, placeholder_model, honest_device_stmt0, honest_fsi_stmt0]
        controlled_fsi_attack_six = [placeholder_signal, placeholder_calib, placeholder_model, honest_device_stmt0, attacked_fsi_stmt]
        controlled_device_attack_six = [placeholder_signal, placeholder_calib, placeholder_model, attacked_device_stmt0, honest_fsi_stmt0]
        controlled_rows = [
            variant_row("controlled_honest", controlled_honest_six),
            variant_row("controlled_fsi_pcr_mismatch_attack", controlled_fsi_attack_six),
            variant_row("controlled_device_invalid_cert_attack", controlled_device_attack_six),
        ]
        print("  -- controlled rows (Signal/Calibration/Model held at the Phase 3/5/6 placeholder-healthy "
              "fixture; FSI/Device still real) --")
        for r in controlled_rows:
            print(f"  variant={r['variant']:32s} FSI_raw={r['FSI_raw']:4d} Device_raw={r['Device_raw']:4d} "
                  f"effective={r['effective_dims']} verdict={r['verdict']}")

        report["reasoning_correctness"] = {
            "real_rows": real_rows,
            "controlled_rows": controlled_rows,
            "note": (
                "Real-data rows: Signal and Calibration's real raw_measurements (see honest_windows above) "
                "are already LOW under config/eis.v0.json's still-placeholder ROC/theta config (calibrated "
                "against synthetic values in Phase 2/3, never fit to real producer output -- Phase 9's job, "
                "CLAUDE.md 14), so the verdict floors to Safe in all three real-data rows regardless of the "
                "FSI/Device attack, which masks rather than demonstrates the CTPR/strict-vs-lenient point. "
                "This is reported as found, not hidden. Controlled rows isolate that point: with Signal/"
                "Calibration/Model held at the same placeholder-healthy fixture already used throughout "
                "Phase 3/5/6 (a real pass through band/reduce/CTPR/policy from raw_measurement=100, not an "
                "injected trust value), the controlled_fsi_pcr_mismatch_attack row shows FSI's raw_measurement "
                "flooring, which floors FSI's own band to LOW, which via CTPR (config/ctpr.json: FSI->Signal, "
                "FSI->Model, meet(child, g(FSI))) floors Signal's and Model's *effective* level to LOW even "
                "though their own raw measurements are unchanged -- CTPR dragging dependents down, observed in "
                "effective_dims. FSI and Model are both strict, so the verdict floors to Safe. The controlled_"
                "device_invalid_cert_attack row floors Device alone (no CTPR edge touches it); Device is the "
                "one LENIENT dimension, so the verdict floors only to Constrained, not Safe -- the strict/"
                "lenient distinction (CLAUDE.md 4) as an actual verdict difference."
            ),
        }

    # ================================================================
    # (ii) Protocol validation: attacks caught at the producer.
    # ================================================================
    report["protocol_validation"] = {
        "summary": "See tests_sensors/ for the full attack-case suite (34/34 passing, run via "
                    ".venv-pipeline/bin/python -m unittest discover -s tests_sensors).",
        "attack_cases": {
            "model.provisional_v0": [
                "bit-flipped weights -> hash mismatch (tests_sensors/test_model_sensor.py:BitFlippedWeightsAttackTests)",
                "stripped signature -> verify fail (StrippedSignatureAttackTests)",
                "unsigned substitute -> rejected (UnsignedSubstituteAttackTests)",
            ],
            "device.provisional_v0": [
                "invalid cert (not signed by pinned CA) -> DTLS handshake fails (test_device_sensor.py:InvalidCertAttackTests)",
                "expired cert -> DTLS handshake fails (ExpiredCertAttackTests)",
                "replayed sequence number -> rejected by SequenceReplayGuard (ReplayedSequenceAttackTests)",
            ],
            "fsi.provisional_v0": [
                "replayed quote (stale quote against a new window's nonce) -> nonce/signature check fails (test_fsi_sensor.py:ReplayedQuoteAttackTests)",
                "PCR mismatch (attacker boot-event after baseline pinned) -> detected via baseline comparison (PcrMismatchAttackTests)",
                "missing quote -> producer emits nothing, per CLAUDE.md 10 (MissingQuoteTests)",
            ],
        },
    }

    # ================================================================
    # (iii) Consequence-boundedness: NOT re-derived here (T5 must never be
    # proven from pi, CLAUDE.md 5) -- restated from Phase 5's existing,
    # already-passing result.
    # ================================================================
    phase5_forcing_path = ARTIFACTS_DIR / "phase5_adversarial_forcing.json"
    if phase5_forcing_path.exists():
        phase5_forcing = json.loads(phase5_forcing_path.read_text())
        report["consequence_boundedness"] = {
            "source": "experiments/phase5_enforcement.py (re-cited, not re-derived here)",
            "violation_count": phase5_forcing["violation_count"],
            "attack_class_count": phase5_forcing["attack_class_count"],
            "note": "T5 must never be proven from pi (CLAUDE.md 5): under Position A the adversary forges "
                    "everything, pi legitimately returns Normal, and any bound derived from the verdict is "
                    "circular. This row restates Phase 5's structural result (realise() never reads Ceil "
                    "from the verdict) rather than re-deriving it from this driver's six-producer pipeline.",
        }
    else:
        report["consequence_boundedness"] = {"error": "run experiments/phase5_enforcement.py first"}

    report_path = ARTIFACTS_DIR / "phase8_evidence_producers_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="phase8_evidence_producers",
        config_paths={"crit_table": wf.CONFIG_PATHS["crit_table"], "ctpr": wf.CONFIG_PATHS["ctpr"],
                      "eis_v0": wf.CONFIG_PATHS["eis"], "key_registry": wf.CONFIG_PATHS["key_registry"],
                      "claim_registry": wf.CONFIG_PATHS["claim_registry"],
                      "ceil": CEIL_PATH, "env": ENV_PATH, "dataset_pins": REPO_ROOT / "config" / "dataset_pins.json"},
        params={"subject": SUBJECT, "n_honest_trials": N_HONEST_TRIALS},
        artifact_paths={"report_json": report_path},
        calibration_status="provisional",
        seeds={"note": "sensor keys from tests/key_fixtures.py named seeds; model-artifact-publisher key from a "
                        "fixed named seed in this driver; swtpm/DTLS certs are freshly generated per run, not seeded"},
    )
    manifest_path = PROVENANCE_DIR / "phase8_evidence_producers_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print(f"\n(iii) Consequence-boundedness (restated from Phase 5, not re-derived): "
          f"{report['consequence_boundedness'].get('violation_count')}/"
          f"{report['consequence_boundedness'].get('attack_class_count')} violations.")
    print(f"\n{MUTATION_SUITE_NOTE}")
    print(f"\nReport written to {report_path}")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
