"""Phase 10: latency evaluation (CLAUDE.md 7, 14).

Measures real per-stage and end-to-end latency on the real pipeline, at the
measured config (config/eis.v1-measured.json), in two configurations:

  Baseline BCI: acquisition -> filtering -> artifact detection -> feature
    extraction -> classification -> predicted intent. No evidence
    production, no kernel, no enforcement.
  BCI + trust architecture: the same pipeline stages PLUS evidence
    production, statement signing, T4 admission, bands -> meet -> CTPR ->
    pi, verdict signing, enforcement accept/clamp/slew/capability write.

Does not modify the kernel, enforcement semantics, crypto rules,
thresholds, or any frozen config -- every stage below calls the real,
unmodified function from trust_kernel/, enforcement/, sensors/,
bci_pipeline/. This is a measurement, not an optimisation pass: no stage is
tuned for speed, and a slow stage is reported slow.

Per-window convention: matches the one already established in
experiments/phase8_evidence_producers.py -- one evidentiary "window" is one
real trial's raw_epoch/feature_vector (this offline substrate has no
independent 100ms-cadence acquisition; the BCI pipeline stages
(artifact detection, feature extraction, classification) already operate
per-trial, which IS this project's per-window granularity for the
evidence/kernel/enforcement layer, per Phase 8's own established
convention).

Acquisition and filtering are session-level BATCH operations in this
offline substrate (loader.load_subject_data loads a whole session at once;
preprocessing's filter step runs once over the whole continuous signal, not
per-trial) -- they are measured and reported as batch costs, not per-trial
ones, and are NOT folded into the per-trial "architecture total" (folding a
one-time session cost into a per-window budget comparison would be
apples-to-oranges against the 100ms recurring-window budget CLAUDE.md 7
actually specifies). This is stated plainly here rather than silently
amortised into a misleading per-window number.

"Filtering" is measured by replaying preprocessing.py's own raw-filter
step (same imported constants, same mne calls) separately from epoching,
so it can be reported as its own stage -- bci_pipeline/preprocessing.py's
build_session_arrays() itself (used everywhere else in this project) is
untouched; this replay exists only for this driver's stage decomposition.

Statement "evidence generation" vs "statement signing" are decomposed by
calling each sensor's own measure_*() function directly for the former,
then trust_kernel.schema.build_statement()/sign_statement() directly for
the latter, instead of going through each Sensor class's build_statement()
convenience wrapper (which bundles both) -- same underlying real functions,
called separately for separated timing, not reimplemented.

Run (needs the pipeline venv):
    .venv-pipeline/bin/python -m experiments.phase10_latency_evaluation
"""

import hashlib
import json
import pathlib
import resource
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import mne
import numpy as np

from bci_pipeline import artifacts as bci_artifacts
from bci_pipeline import classifier as bci_classifier
from bci_pipeline import features as bci_features
from bci_pipeline import loader as bci_loader
from bci_pipeline import pipeline as bci_pipeline_mod
from bci_pipeline import preprocessing as bci_preprocessing
from enforcement import clamp
from enforcement.capability import ActuatorCapability, SimulatedActuator
from enforcement.slew import SlewState
from latency import measurement as lm
from provenance import manifest as manifest_mod
from sensors import calibration_sensor, device_certs, device_sensor, fsi_sensor, fsi_swtpm, model_sensor, signal_sensor
from tests import key_fixtures as kf
from trust_kernel import bands as bands_mod
from trust_kernel import ctpr as ctpr_mod
from trust_kernel import policy as policy_mod
from trust_kernel import schema, sign

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"
CONFIG_DIR = REPO_ROOT / "config"
MEASURED_CONFIG_PATH = CONFIG_DIR / "eis.v1-measured.json"
CEIL_PATH = CONFIG_DIR / "ceil.json"
ENV_PATH = CONFIG_DIR / "env.json"

SUBJECT = 1
N_TRIALS = 200          # per-trial stages that don't require real TPM ops
N_TRIALS_FSI = 30       # includes a real fresh swtpm quote each iteration -- smaller N, disclosed
N_WARMUP = 8
N_ACQ_FILT_REPEATS = 3  # session-level batch ops; a few repeats for variance only

WINDOW_PERIOD_MS = schema.WINDOW_PERIOD_MS         # 100
EVIDENCE_DEADLINE_MS = schema.EVIDENCE_DEADLINE_MS  # 60 (Delta(w))
KERNEL_BUDGET_MS = schema.KERNEL_BUDGET_MS          # 5 (kappa)
DECISION_PATH_BUDGET_MS = 67.0                      # CLAUDE.md 7: "Decision path <= 67ms of the 100ms window"


class Timer:
    def __init__(self, store: dict, name: str):
        self.store, self.name = store, name

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        dt_ms = (time.perf_counter() - self.t0) * 1000.0
        self.store.setdefault(self.name, []).append(dt_ms)


def _write_json(obj, path):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


# ==========================================================================
# Session-level setup: real subject data, real signed artifacts, real
# established DTLS/TPM sessions. Everything here is a ONE-TIME cost, done
# before any timed loop -- matches how a real deployed system would
# establish these once per session, not re-derive them every window.
# ==========================================================================

def build_context(pins):
    result = bci_pipeline_mod.run_subject(SUBJECT, pins=pins)
    train, test = result["train"], result["test"]
    sfreq = train["arrays"]["sfreq"]
    n_test = test["n_trials"]

    enrollment_stats = calibration_sensor.compute_enrollment_stats(train["features"])

    artifact_seed = hashlib.sha256(b"phase10-model-artifact-publisher-seed").digest()
    artifact_pk, artifact_sk = sign.keypair_from_seed(artifact_seed)
    artifact_bytes = model_sensor.serialize_classifier_artifact(result["classifier"])
    signing_record = model_sensor.sign_artifact(artifact_sk, artifact_bytes)

    ca = device_certs.make_ca()
    valid_server_cert = device_certs.make_valid_server_cert(ca)
    handshake_result = device_sensor.run_dtls_handshake(valid_server_cert["combined_pem"], ca["cert_pem"])
    replay_guard = device_sensor.SequenceReplayGuard()

    keys = {d: kf.keypair_for(sid) for d, sid in (
        ("Signal", signal_sensor.SIGNAL_SOURCE_ID),
        ("Calibration", calibration_sensor.CALIBRATION_SOURCE_ID),
        ("Model", model_sensor.MODEL_SOURCE_ID),
        ("Device", device_sensor.DEVICE_SOURCE_ID),
        ("FSI", fsi_sensor.FSI_SOURCE_ID),
    )}
    kernel_pk, kernel_sk = kf.kernel_keypair()

    key_registry = schema.load_key_registry(CONFIG_DIR / "key_registry.json")
    claim_registry = schema.load_claim_registry(CONFIG_DIR / "claim_registry.json")
    _, eis_derived = bands_mod.load_eis_config(MEASURED_CONFIG_PATH)
    _, ctpr_edges = ctpr_mod.load_ctpr_config(CONFIG_DIR / "ctpr.json")
    _, strict, lenient = policy_mod.load_crit_table(CONFIG_DIR / "crit_table.json")
    ceil, env = clamp.load_envelope_configs(CEIL_PATH, ENV_PATH)

    return {
        "sfreq": sfreq, "n_test": n_test,
        "test_raw_epochs": test["arrays"]["raw_epochs"],
        "test_filtered_epochs": test["arrays"]["filtered_epochs"],
        "test_eog_epochs": test["arrays"]["eog_epochs"],
        "fitted_features": result["fitted_features"],
        "clf": result["classifier"],
        "enrollment_stats": enrollment_stats,
        "artifact_bytes": artifact_bytes, "artifact_pk": artifact_pk, "signing_record": signing_record,
        "handshake_result": handshake_result, "replay_guard": replay_guard,
        "keys": keys, "kernel_pk": kernel_pk, "kernel_sk": kernel_sk,
        "key_registry": key_registry, "claim_registry": claim_registry,
        "eis_derived": eis_derived, "ctpr_edges": ctpr_edges, "strict": strict, "lenient": lenient,
        "ceil": ceil, "env": env,
        "crit_table_hash": policy_mod.crit_table_hash(CONFIG_DIR / "crit_table.json"),
        "ctpr_config_hash": ctpr_mod.ctpr_config_hash(CONFIG_DIR / "ctpr.json"),
        "roc_config_hash": bands_mod.roc_config_hash(MEASURED_CONFIG_PATH),
        "claim_registry_hash": schema.claim_registry_hash(CONFIG_DIR / "claim_registry.json"),
        "key_registry_hash": schema.key_registry_hash(CONFIG_DIR / "key_registry.json"),
    }


# ==========================================================================
# Acquisition + filtering: session-level batch costs, measured by replaying
# loader.load_subject_data() and preprocessing.py's own filter step (same
# constants) separately from epoching, for stage decomposition only.
# ==========================================================================

def measure_acquisition_and_filtering(pins):
    acq_ms, filt_ms = [], []
    for _ in range(N_ACQ_FILT_REPEATS):
        t0 = time.perf_counter()
        mne_data, _verified = bci_loader.load_subject_data(SUBJECT, pins=pins)
        acq_ms.append((time.perf_counter() - t0) * 1000.0)

        session_key = next(s for s in mne_data if "test" in s)
        runs = mne_data[session_key]
        raws = [runs[k].copy() for k in sorted(runs)]
        raw = mne.concatenate_raws(raws, verbose=False)
        eeg_picks = mne.pick_types(raw.info, eeg=True, eog=False, stim=False)

        t0 = time.perf_counter()
        raw_f = raw.copy().filter(
            l_freq=bci_preprocessing.BANDPASS_LOW_HZ, h_freq=bci_preprocessing.BANDPASS_HIGH_HZ,
            picks=eeg_picks, verbose=False,
        )
        raw_f.notch_filter(freqs=[bci_preprocessing.NOTCH_HZ], picks=eeg_picks, verbose=False)
        filt_ms.append((time.perf_counter() - t0) * 1000.0)
    return {"acquisition_ms": lm.p50_p99(acq_ms), "filtering_ms": lm.p50_p99(filt_ms)}


# ==========================================================================
# Per-trial baseline stages (shared by both configurations, called
# identically in both -- no duplicated logic).
# ==========================================================================

def run_baseline_stages(ctx, idx, timings):
    eog_1 = ctx["test_eog_epochs"][idx:idx + 1]
    filtered_1 = ctx["test_filtered_epochs"][idx:idx + 1]

    with Timer(timings, "artifact_detection"):
        bci_artifacts.detect_eog_artifacts(eog_1, ctx["sfreq"])

    with Timer(timings, "feature_extraction"):
        feat = bci_features.transform_features(ctx["fitted_features"], filtered_1)

    with Timer(timings, "classification"):
        bci_classifier.predict_intent(ctx["clf"], feat)

    return feat[0]


# ==========================================================================
# Architecture-only stages: evidence generation, signing, admission, kernel
# decision, verdict signing, enforcement. FSI excluded here (separate loop,
# smaller N -- see run_fsi_trial).
# ==========================================================================

def _sign_stmt(ctx, dim, source_id, boundary, claim_type, raw_measurement, window_id):
    fields = schema.build_statement(
        key_id=source_id, source_id=source_id, boundary=boundary, claim_type=claim_type,
        raw_measurement=raw_measurement, window_id=window_id, claimed_at=0,
    )
    _, sk = ctx["keys"][dim]
    return schema.sign_statement(sk, fields)


def run_architecture_stages_excl_fsi(ctx, idx, window_id, timings, feat):
    raw_epoch_1 = ctx["test_raw_epochs"][idx]

    with Timer(timings, "evidence_generation_signal"):
        raw_signal = signal_sensor.measure_signal_quality(raw_epoch_1, ctx["sfreq"])
    with Timer(timings, "evidence_generation_calibration"):
        raw_calib = calibration_sensor.measure_calibration_drift(feat, ctx["enrollment_stats"])
    with Timer(timings, "evidence_generation_model"):
        raw_model = model_sensor.measure_model_integrity(ctx["artifact_bytes"], ctx["artifact_pk"], ctx["signing_record"])
    with Timer(timings, "evidence_generation_device"):
        seq_ok = ctx["replay_guard"].check_and_record(window_id)
        raw_device = device_sensor.measure_device_link(ctx["handshake_result"], seq_ok)

    stmts = {}
    with Timer(timings, "statement_signing_signal"):
        stmts["Signal"] = _sign_stmt(ctx, "Signal", signal_sensor.SIGNAL_SOURCE_ID, signal_sensor.SIGNAL_BOUNDARY,
                                      signal_sensor.SIGNAL_CLAIM_TYPE, raw_signal, window_id)
    with Timer(timings, "statement_signing_calibration"):
        stmts["Calibration"] = _sign_stmt(ctx, "Calibration", calibration_sensor.CALIBRATION_SOURCE_ID,
                                           calibration_sensor.CALIBRATION_BOUNDARY,
                                           calibration_sensor.CALIBRATION_CLAIM_TYPE, raw_calib, window_id)
    with Timer(timings, "statement_signing_model"):
        stmts["Model"] = _sign_stmt(ctx, "Model", model_sensor.MODEL_SOURCE_ID, model_sensor.MODEL_BOUNDARY,
                                     model_sensor.MODEL_CLAIM_TYPE, raw_model, window_id)
    with Timer(timings, "statement_signing_device"):
        stmts["Device"] = _sign_stmt(ctx, "Device", device_sensor.DEVICE_SOURCE_ID, device_sensor.DEVICE_BOUNDARY,
                                      device_sensor.DEVICE_CLAIM_TYPE, raw_device, window_id)

    return stmts


def run_admission_kernel_verdict_enforcement(ctx, window_id, timings, stmts, slew_state, actuator, cap):
    with Timer(timings, "evidence_admission"):
        admitted = []
        for stmt in stmts.values():
            r = schema.admit_statement(
                stmt, key_registry=ctx["key_registry"], claim_registry=ctx["claim_registry"],
                current_window_id=window_id, window_open_time_ms=0, arrival_time_ms=1,
            )
            if r.accepted:
                admitted.append(stmt)

    with Timer(timings, "kernel_decision"):
        by_dim = {d: [] for d in bands_mod.DIMENSIONS}
        for stmt in admitted:
            claim_entry = ctx["claim_registry"]["claims"][stmt["claim_type"]]
            theta1, theta2, cap_level = ctx["eis_derived"][stmt["claim_type"]]
            s = bands_mod.score(1, stmt["raw_measurement"])
            by_dim[claim_entry["dimension"]].append(bands_mod.band(s, theta1, theta2, cap_level))
        raw_dims = {d: (bands_mod.reduce_dimension(c) if c else bands_mod.reduce_dimension([None]))
                    for d, c in by_dim.items()}
        effective = ctpr_mod.apply_ctpr(raw_dims, ctx["ctpr_edges"])
        verdict = policy_mod.policy(effective, ctx["strict"], ctx["lenient"])

    with Timer(timings, "verdict_signing"):
        evidence_root = schema.build_evidence_root(admitted)
        vfields = schema.build_verdict(
            window_id=window_id, evidence_root=evidence_root, effective_dims=effective, verdict=verdict,
            policy_version="v1",
            crit_table_hash=ctx["crit_table_hash"], ctpr_config_hash=ctx["ctpr_config_hash"],
            roc_config_hash=ctx["roc_config_hash"], claim_registry_hash=ctx["claim_registry_hash"],
            key_registry_hash=ctx["key_registry_hash"], calibration_status="provisional",
            issued_at=62, expires_at=170,
        )
        verdict_obj = schema.sign_verdict(ctx["kernel_sk"], vfields)

    with Timer(timings, "enforcement"):
        decision = clamp.accept_and_clamp(
            verdict_obj, ctx["kernel_pk"], now_ms=100, cache=clamp.AcceptCache(), env=ctx["env"], ceil=ctx["ceil"],
        )
        if decision.accepted and decision.envelope is not None:
            cmd = slew_state.step(decision.envelope)
            actuator.write(cap, cmd)

    return verdict, admitted


# ==========================================================================
# Configuration loops.
# ==========================================================================

def run_baseline_loop(ctx, n):
    timings = {}
    for i in range(N_WARMUP):
        run_baseline_stages(ctx, i % ctx["n_test"], {})
    t0 = time.perf_counter()
    ru0 = resource.getrusage(resource.RUSAGE_SELF)
    for i in range(n):
        run_baseline_stages(ctx, i % ctx["n_test"], timings)
    ru1 = resource.getrusage(resource.RUSAGE_SELF)
    wall_s = time.perf_counter() - t0
    return timings, _rusage_delta(ru0, ru1), wall_s


def run_architecture_loop(ctx, n):
    timings = {}
    slew_state = SlewState()
    cap = ActuatorCapability()
    actuator = SimulatedActuator(cap)

    def one(i, store):
        window_id = 50_000 + i
        idx = i % ctx["n_test"]
        feat = run_baseline_stages(ctx, idx, store)
        stmts = run_architecture_stages_excl_fsi(ctx, idx, window_id, store, feat)
        run_admission_kernel_verdict_enforcement(ctx, window_id, store, stmts, slew_state, actuator, cap)

    for i in range(N_WARMUP):
        one(i, {})
    t0 = time.perf_counter()
    ru0 = resource.getrusage(resource.RUSAGE_SELF)
    for i in range(n):
        one(N_WARMUP + i, timings)
    ru1 = resource.getrusage(resource.RUSAGE_SELF)
    wall_s = time.perf_counter() - t0
    return timings, _rusage_delta(ru0, ru1), wall_s


def run_fsi_loop(ctx, n):
    """FSI evidence generation requires a fresh, real swtpm quote each
    window (a genuine per-window TPM operation, unlike Device's reused
    handshake) -- measured separately at a smaller N, disclosed rather than
    silently mixed into the larger-N stages above."""
    timings = {}
    with fsi_swtpm.SwtpmSession() as session:
        baseline = fsi_sensor.provision_fsi_baseline(session, ctx["artifact_bytes"])

        def one(i, store):
            nonce = hashlib.sha256(f"phase10-fsi-{i}".encode()).hexdigest()[:40]
            with Timer(store, "evidence_generation_fsi"):
                quote = session.quote(baseline["ak_ctx"], nonce)
                evaluation = fsi_sensor.evaluate_quote(session, baseline, quote, nonce)
            with Timer(store, "statement_signing_fsi"):
                _sign_stmt(ctx, "FSI", fsi_sensor.FSI_SOURCE_ID, fsi_sensor.FSI_BOUNDARY,
                           fsi_sensor.FSI_CLAIM_TYPE, evaluation["raw_measurement"], window_id=60_000 + i)

        for i in range(min(N_WARMUP, 3)):
            one(i, {})
        t0 = time.perf_counter()
        ru0 = resource.getrusage(resource.RUSAGE_SELF)
        for i in range(n):
            one(3 + i, timings)
        ru1 = resource.getrusage(resource.RUSAGE_SELF)
        wall_s = time.perf_counter() - t0
    return timings, _rusage_delta(ru0, ru1), wall_s


def _rusage_delta(ru0, ru1):
    return {
        "cpu_user_s": ru1.ru_utime - ru0.ru_utime,
        "cpu_system_s": ru1.ru_stime - ru0.ru_stime,
        "max_rss_kb_end": ru1.ru_maxrss,
    }


# ==========================================================================
# Deadline-invariant demonstration: a hung/slow producer must never delay
# the verdict, and the absent dimension must read LOW.
# ==========================================================================

def hung_producer_demonstration(ctx):
    window_id = 70_001

    def make_task(dim, fn):
        def task():
            raw = fn()
            source_id, boundary, claim_type = {
                "Signal": (signal_sensor.SIGNAL_SOURCE_ID, signal_sensor.SIGNAL_BOUNDARY, signal_sensor.SIGNAL_CLAIM_TYPE),
                "Calibration": (calibration_sensor.CALIBRATION_SOURCE_ID, calibration_sensor.CALIBRATION_BOUNDARY,
                                calibration_sensor.CALIBRATION_CLAIM_TYPE),
                "Model": (model_sensor.MODEL_SOURCE_ID, model_sensor.MODEL_BOUNDARY, model_sensor.MODEL_CLAIM_TYPE),
                "Device": (device_sensor.DEVICE_SOURCE_ID, device_sensor.DEVICE_BOUNDARY, device_sensor.DEVICE_CLAIM_TYPE),
            }[dim]
            return _sign_stmt(ctx, dim, source_id, boundary, claim_type, raw, window_id)
        return task

    idx = 0
    feat = ctx["test_filtered_epochs"][idx:idx + 1]
    feat = bci_features.transform_features(ctx["fitted_features"], feat)[0]
    raw_epoch_1 = ctx["test_raw_epochs"][idx]

    def hung_signal():
        time.sleep(2.0)  # never responds within Delta(w) -- simulates a genuinely hung producer
        return signal_sensor.measure_signal_quality(raw_epoch_1, ctx["sfreq"])

    def real_calibration():
        return calibration_sensor.measure_calibration_drift(feat, ctx["enrollment_stats"])

    def real_model():
        return model_sensor.measure_model_integrity(ctx["artifact_bytes"], ctx["artifact_pk"], ctx["signing_record"])

    def real_device():
        seq_ok = ctx["replay_guard"].check_and_record(900_000)
        return device_sensor.measure_device_link(ctx["handshake_result"], seq_ok)

    deadline_s = EVIDENCE_DEADLINE_MS / 1000.0

    # Control window: all four producers respond normally.
    control_tasks = {
        "Signal": make_task("Signal", lambda: signal_sensor.measure_signal_quality(raw_epoch_1, ctx["sfreq"])),
        "Calibration": make_task("Calibration", real_calibration),
        "Model": make_task("Model", real_model),
        "Device": make_task("Device", real_device),
    }
    t0 = time.perf_counter()
    control_stmts = lm.collect_within_deadline(control_tasks, deadline_s)
    control_collect_ms = (time.perf_counter() - t0) * 1000.0

    # Hung window: Signal never responds in time.
    hung_tasks = {
        "Signal": make_task("Signal", hung_signal),
        "Calibration": make_task("Calibration", real_calibration),
        "Model": make_task("Model", real_model),
        "Device": make_task("Device", real_device),
    }
    t0 = time.perf_counter()
    hung_stmts = lm.collect_within_deadline(hung_tasks, deadline_s)
    hung_collect_ms = (time.perf_counter() - t0) * 1000.0

    def decide(stmts, window_id):
        admission = {}
        for dim, stmt in stmts.items():
            r = schema.admit_statement(
                stmt, key_registry=ctx["key_registry"], claim_registry=ctx["claim_registry"],
                current_window_id=window_id, window_open_time_ms=0, arrival_time_ms=1,
            )
            admission[dim] = r.accepted
        by_dim = {d: [] for d in bands_mod.DIMENSIONS}
        for dim, stmt in stmts.items():
            if not admission[dim]:
                continue
            claim_entry = ctx["claim_registry"]["claims"][stmt["claim_type"]]
            theta1, theta2, cap_level = ctx["eis_derived"][stmt["claim_type"]]
            s = bands_mod.score(1, stmt["raw_measurement"])
            by_dim[claim_entry["dimension"]].append(bands_mod.band(s, theta1, theta2, cap_level))
        raw_dims = {d: (bands_mod.reduce_dimension(c) if c else bands_mod.reduce_dimension([None]))
                    for d, c in by_dim.items()}
        effective = ctpr_mod.apply_ctpr(raw_dims, ctx["ctpr_edges"])
        verdict = policy_mod.policy(effective, ctx["strict"], ctx["lenient"])
        return {"admission": admission, "effective_signal": effective["Signal"].name, "verdict": verdict.name}

    control_result = decide(control_stmts, window_id)
    hung_result = decide(hung_stmts, window_id)

    return {
        "deadline_ms": EVIDENCE_DEADLINE_MS,
        "control": {**control_result, "collection_wall_ms": control_collect_ms,
                    "statements_collected": sorted(control_stmts.keys())},
        "hung": {**hung_result, "collection_wall_ms": hung_collect_ms,
                 "statements_collected": sorted(hung_stmts.keys())},
        "verdict_still_issued_despite_hung_producer": hung_result["verdict"] in ("Safe", "Constrained", "Normal"),
        "hung_dimension_reads_low": hung_result["effective_signal"] == "LOW",
        "signal_absent_from_hung_admission": "Signal" not in hung_stmts,
        "collection_latency_bounded_by_deadline_not_hang_duration": hung_collect_ms < 2000.0,
        "note": (
            "hung_signal() sleeps 2.0s (2000ms) before it would even compute a value -- far longer "
            "than Delta(w)=60ms. collect_within_deadline() never waits for it: the hung thread is "
            "simply abandoned (daemon=True) once the shared 60ms budget elapses, and admission/kernel/"
            "policy proceed on whatever arrived. The invariant under test is "
            "collection_latency_bounded_by_deadline_not_hang_duration -- collection wall time is ~60ms, "
            "not ~2000ms, regardless of the hung producer's real behaviour."
        ),
    }


# ==========================================================================
# Budget verification and mutation checks.
# ==========================================================================

def check_budgets(baseline_stats, architecture_stats, fsi_stats):
    decision_path_stages = [
        "evidence_generation_signal", "evidence_generation_calibration", "evidence_generation_model",
        "evidence_generation_device", "statement_signing_signal", "statement_signing_calibration",
        "statement_signing_model", "statement_signing_device", "evidence_admission",
        "kernel_decision", "verdict_signing", "enforcement",
    ]
    decision_path_p99_ms = sum(architecture_stats[s]["p99_ms"] for s in decision_path_stages)

    admission_path_stages = [
        "evidence_generation_signal", "evidence_generation_calibration", "evidence_generation_model",
        "evidence_generation_device", "statement_signing_signal", "statement_signing_calibration",
        "statement_signing_model", "statement_signing_device",
    ]
    admission_path_p99_ms = sum(architecture_stats[s]["p99_ms"] for s in admission_path_stages)

    fsi_p99_ms = fsi_stats["evidence_generation_fsi"]["p99_ms"] + fsi_stats["statement_signing_fsi"]["p99_ms"]
    admission_path_p99_ms_incl_fsi = admission_path_p99_ms + fsi_p99_ms
    decision_path_p99_ms_incl_fsi = decision_path_p99_ms + fsi_p99_ms

    return {
        # 4-producer sums (Signal/Calibration/Model/Device): FSI was measured in a
        # separate loop (real swtpm quotes, smaller N -- see fsi_stats) and is
        # NOT included here.
        "decision_path_le_67ms_excl_fsi": lm.budget_compliance(decision_path_p99_ms, DECISION_PATH_BUDGET_MS),
        "kernel_decision_le_kappa_5ms": lm.budget_compliance(architecture_stats["kernel_decision"]["p99_ms"], KERNEL_BUDGET_MS),
        "evidence_generation_and_signing_le_delta_60ms_excl_fsi": lm.budget_compliance(admission_path_p99_ms, EVIDENCE_DEADLINE_MS),
        # Headline result: FSI's real per-window cost (a fresh swtpm quote,
        # measured, not assumed) folded in. This is the number that actually
        # answers "does the real system meet CLAUDE.md 7's budgets" -- the
        # excl_fsi checks above exist only because FSI's measurement loop is
        # structurally separate, not because FSI is exempt from the budget.
        "decision_path_le_67ms_INCLUDING_FSI": lm.budget_compliance(decision_path_p99_ms_incl_fsi, DECISION_PATH_BUDGET_MS),
        "evidence_generation_and_signing_le_delta_60ms_INCLUDING_FSI": lm.budget_compliance(admission_path_p99_ms_incl_fsi, EVIDENCE_DEADLINE_MS),
        "decision_path_stages_summed": decision_path_stages,
        "admission_path_stages_summed": admission_path_stages,
        "fsi_open_question_for_the_pi": (
            "FSI's claim_registry.json provenance_note describes it as attesting firmware/software "
            "state 'as measured at boot... boot-time only' -- a real deployment may not need a fresh "
            "TPM quote every 100ms window (unlike Signal/Calibration/Model/Device, genuinely "
            "per-window measurements), in which case the INCLUDING_FSI violation above is an "
            "artifact of this driver's uniform per-window convention applied to a claim whose real "
            "cadence may be coarser, not a genuine architectural problem. Not resolved here -- this "
            "driver measures FSI's actual per-invocation cost and reports the consequence of "
            "invoking it every window, rather than assuming a coarser cadence without evidence."
        ),
    }


def run_mutation_checks():
    latency_proc = subprocess.run(
        [sys.executable, "-m", "harnesses.mutation_check_latency"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    core_proc = subprocess.run(
        [sys.executable, "-m", "harnesses.mutation_check"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    return {
        "latency_kill_rate_line": latency_proc.stdout.splitlines()[0] if latency_proc.stdout else latency_proc.stderr[-2000:],
        "latency_passed": latency_proc.returncode == 0,
        "pure_core_kill_rate_line": core_proc.stdout.splitlines()[0] if core_proc.stdout else None,
        "pure_core_unaffected": core_proc.returncode == 0,
    }


# ==========================================================================
# Main.
# ==========================================================================

def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    pins = bci_loader.load_pins()

    print("Session-level setup (real subject-1 pipeline, real signed artifact, "
          "real DTLS handshake)...", flush=True)
    ctx = build_context(pins)

    print("Acquisition + filtering (batch, session-level, few repeats)...", flush=True)
    acq_filt = measure_acquisition_and_filtering(pins)

    print(f"\nBaseline BCI loop (N={N_TRIALS}, {N_WARMUP} warmup discarded)...", flush=True)
    baseline_timings, baseline_ru, baseline_wall_s = run_baseline_loop(ctx, N_TRIALS)
    baseline_stats = {k: lm.p50_p99(v) for k, v in baseline_timings.items()}

    print(f"\nBCI + trust architecture loop (N={N_TRIALS}, {N_WARMUP} warmup discarded, "
          "measured config)...", flush=True)
    architecture_timings, architecture_ru, architecture_wall_s = run_architecture_loop(ctx, N_TRIALS)
    architecture_stats = {k: lm.p50_p99(v) for k, v in architecture_timings.items()}

    print(f"\nFSI loop (N={N_TRIALS_FSI}, real swtpm quotes)...", flush=True)
    fsi_timings, fsi_ru, fsi_wall_s = run_fsi_loop(ctx, N_TRIALS_FSI)
    fsi_stats = {k: lm.p50_p99(v) for k, v in fsi_timings.items()}

    print("\nEnd-to-end totals...", flush=True)
    baseline_total_stage_names = ["artifact_detection", "feature_extraction", "classification"]
    architecture_total_stage_names = baseline_total_stage_names + [
        "evidence_generation_signal", "evidence_generation_calibration", "evidence_generation_model",
        "evidence_generation_device", "statement_signing_signal", "statement_signing_calibration",
        "statement_signing_model", "statement_signing_device", "evidence_admission",
        "kernel_decision", "verdict_signing", "enforcement",
    ]
    baseline_total_per_trial = [sum(baseline_timings[s][i] for s in baseline_total_stage_names)
                                 for i in range(N_TRIALS)]
    architecture_total_per_trial = [sum(architecture_timings[s][i] for s in architecture_total_stage_names)
                                     for i in range(N_TRIALS)]
    baseline_total_stats = lm.p50_p99(baseline_total_per_trial)
    architecture_total_stats = lm.p50_p99(architecture_total_per_trial)
    overhead = lm.stage_overhead(baseline_total_stats, architecture_total_stats)
    overhead_fraction = {
        "p50": lm.overhead_fraction_of_window(overhead["p50_overhead_ms"], WINDOW_PERIOD_MS),
        "p99": lm.overhead_fraction_of_window(overhead["p99_overhead_ms"], WINDOW_PERIOD_MS),
    }

    per_stage_overhead = {}
    for stage in architecture_total_stage_names:
        if stage in baseline_stats:
            per_stage_overhead[stage] = lm.stage_overhead(baseline_stats[stage], architecture_stats[stage])
        else:
            per_stage_overhead[stage] = {
                "p50_overhead_ms": architecture_stats[stage]["p50_ms"],
                "p99_overhead_ms": architecture_stats[stage]["p99_ms"],
                "mean_overhead_ms": architecture_stats[stage]["mean_ms"],
                "note": "stage does not exist in baseline (new in architecture) -- overhead == stage's own latency",
            }

    print(f"  baseline total:      p50={baseline_total_stats['p50_ms']:.3f}ms p99={baseline_total_stats['p99_ms']:.3f}ms")
    print(f"  architecture total:  p50={architecture_total_stats['p50_ms']:.3f}ms p99={architecture_total_stats['p99_ms']:.3f}ms")
    print(f"  overhead:            p50={overhead['p50_overhead_ms']:.3f}ms ({overhead_fraction['p50']:.4%} of 100ms) "
          f"p99={overhead['p99_overhead_ms']:.3f}ms ({overhead_fraction['p99']:.4%} of 100ms)")

    print("\nBudget verification against CLAUDE.md 7's frozen timing parameters...", flush=True)
    budgets = check_budgets(baseline_stats, architecture_stats, fsi_stats)
    for k, v in budgets.items():
        if isinstance(v, dict) and "violated" in v:
            print(f"  {k}: measured_p99={v['measured_p99_ms']:.3f}ms budget={v['budget_ms']}ms "
                  f"margin={v['margin_ms']:.3f}ms VIOLATED={v['violated']}")

    print("\nDeadline-invariant demonstration (hung producer)...", flush=True)
    hung_demo = hung_producer_demonstration(ctx)
    print(f"  control: collected={hung_demo['control']['statements_collected']} "
          f"collection_wall_ms={hung_demo['control']['collection_wall_ms']:.3f} "
          f"verdict={hung_demo['control']['verdict']}")
    print(f"  hung:    collected={hung_demo['hung']['statements_collected']} "
          f"collection_wall_ms={hung_demo['hung']['collection_wall_ms']:.3f} "
          f"verdict={hung_demo['hung']['verdict']} "
          f"Signal_effective={hung_demo['hung']['effective_signal']}")
    print(f"  verdict_still_issued={hung_demo['verdict_still_issued_despite_hung_producer']} "
          f"hung_dimension_reads_low={hung_demo['hung_dimension_reads_low']} "
          f"bounded_by_deadline={hung_demo['collection_latency_bounded_by_deadline_not_hang_duration']}")

    print("\nMutation checks...", flush=True)
    mutation = run_mutation_checks()

    throughput = {
        "baseline_windows_per_s": N_TRIALS / baseline_wall_s,
        "architecture_windows_per_s": N_TRIALS / architecture_wall_s,
        "fsi_windows_per_s": N_TRIALS_FSI / fsi_wall_s,
    }

    report = {
        "task": "phase10_latency_evaluation",
        "subject": SUBJECT, "n_trials": N_TRIALS, "n_trials_fsi": N_TRIALS_FSI, "n_warmup": N_WARMUP,
        "measured_config_path": str(MEASURED_CONFIG_PATH),
        "measured_config_roc_config_hash": ctx["roc_config_hash"],
        "acquisition_and_filtering_batch": acq_filt,
        "baseline_per_stage": baseline_stats,
        "architecture_per_stage": architecture_stats,
        "fsi_per_stage": fsi_stats,
        "baseline_total_per_trial_ms": baseline_total_stats,
        "architecture_total_per_trial_ms": architecture_total_stats,
        "headline_overhead": overhead,
        "headline_overhead_fraction_of_100ms_window": overhead_fraction,
        "per_stage_overhead": per_stage_overhead,
        "budget_verification": budgets,
        "hung_producer_demonstration": hung_demo,
        "cpu_memory": {"baseline": baseline_ru, "architecture": architecture_ru, "fsi_loop": fsi_ru},
        "throughput": throughput,
        "mutation": mutation,
    }
    report_path = ARTIFACTS_DIR / "phase10_latency_evaluation_report.json"
    _write_json(report, report_path)

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="phase10_latency_evaluation",
        config_paths={"eis_v1_measured": MEASURED_CONFIG_PATH, "crit_table": CONFIG_DIR / "crit_table.json",
                      "ctpr": CONFIG_DIR / "ctpr.json", "claim_registry": CONFIG_DIR / "claim_registry.json",
                      "key_registry": CONFIG_DIR / "key_registry.json", "ceil": CEIL_PATH, "env": ENV_PATH,
                      "dataset_pins": CONFIG_DIR / "dataset_pins.json"},
        params={"subject": SUBJECT, "n_trials": N_TRIALS, "n_trials_fsi": N_TRIALS_FSI, "n_warmup": N_WARMUP},
        artifact_paths={"report": report_path},
        calibration_status="provisional",
        seeds={"note": "model artifact-signing key from a fixed named seed in this driver; "
                        "DTLS/swtpm sessions freshly generated per run, not seeded"},
    )
    manifest_path = PROVENANCE_DIR / "phase10_latency_evaluation_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print(f"\nReport written to {report_path}")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
