"""Shared window/verdict construction helpers for Phase 3/4 tests and
experiments. Provisional demo material (see tests/key_fixtures.py) -- not
imported by trust_kernel/ or evidence_plane/.
"""

import pathlib

from trust_kernel import ctpr as ctpr_mod, policy as policy_mod, schema
from trust_kernel.bands import DIMENSIONS, band, load_eis_config, reduce_dimension, roc_config_hash, score as score_fn
from tests import key_fixtures as kf

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"

CONFIG_PATHS = {
    "crit_table": CONFIG_DIR / "crit_table.json",
    "ctpr": CONFIG_DIR / "ctpr.json",
    "eis": CONFIG_DIR / "eis.v0.json",
    "claim_registry": CONFIG_DIR / "claim_registry.json",
    "key_registry": CONFIG_DIR / "key_registry.json",
}

CLAIM_TYPE_BY_DIM = {
    "Signal": "signal.provisional_v0", "Model": "model.provisional_v0",
    "Calibration": "calibration.provisional_v0",
    "Device": "device.provisional_v0", "FSI": "fsi.provisional_v0",
    "ActuationFidelity": "actuationfidelity.provisional_v0",
}
SOURCE_ID_BY_DIM = {
    "Signal": "signal_sensor_v0", "Model": "model_sensor_v0",
    "Calibration": "calibration_sensor_v0", "Device": "device_sensor_v0", "FSI": "fsi_sensor_v0",
    "ActuationFidelity": "actuationfidelity_sensor_v0",
}


def healthy_signed_statement(dimension, window_id, raw_measurement=100):
    source_id = SOURCE_ID_BY_DIM[dimension]
    _, sk = kf.keypair_for(source_id)
    fields = schema.build_statement(
        key_id=source_id, source_id=source_id, boundary="TB2",
        claim_type=CLAIM_TYPE_BY_DIM[dimension], raw_measurement=raw_measurement,
        window_id=window_id, claimed_at=0,
    )
    return schema.sign_statement(sk, fields)


def healthy_window(window_id, raw_measurement=100):
    return [healthy_signed_statement(d, window_id, raw_measurement) for d in DIMENSIONS]


def compute_verdict(statements, config_paths=CONFIG_PATHS):
    _, eis_derived = load_eis_config(config_paths["eis"])
    _, edges = ctpr_mod.load_ctpr_config(config_paths["ctpr"])
    _, strict, lenient = policy_mod.load_crit_table(config_paths["crit_table"])
    claim_registry = schema.load_claim_registry(config_paths["claim_registry"])

    by_dimension = {d: [] for d in DIMENSIONS}
    for stmt in statements:
        claim_entry = claim_registry["claims"][stmt["claim_type"]]
        theta1, theta2, cap = eis_derived[stmt["claim_type"]]
        s = score_fn(1, stmt["raw_measurement"])
        by_dimension[claim_entry["dimension"]].append(band(s, theta1, theta2, cap))

    raw_dims = {d: reduce_dimension(c) if c else reduce_dimension([None]) for d, c in by_dimension.items()}
    effective = ctpr_mod.apply_ctpr(raw_dims, edges)
    verdict = policy_mod.policy(effective, strict, lenient)
    return effective, verdict


def issue_signed_verdict(statements, window_id, config_paths=CONFIG_PATHS,
                          issued_at=62, expires_at=170, calibration_status="provisional"):
    effective, verdict = compute_verdict(statements, config_paths)
    evidence_root = schema.build_evidence_root(statements)
    vfields = schema.build_verdict(
        window_id=window_id, evidence_root=evidence_root, effective_dims=effective, verdict=verdict,
        policy_version="v1",
        crit_table_hash=policy_mod.crit_table_hash(config_paths["crit_table"]),
        ctpr_config_hash=ctpr_mod.ctpr_config_hash(config_paths["ctpr"]),
        roc_config_hash=roc_config_hash(config_paths["eis"]),
        claim_registry_hash=schema.claim_registry_hash(config_paths["claim_registry"]),
        key_registry_hash=schema.key_registry_hash(config_paths["key_registry"]),
        calibration_status=calibration_status, issued_at=issued_at, expires_at=expires_at,
    )
    _, kernel_sk = kf.kernel_keypair()
    return schema.sign_verdict(kernel_sk, vfields)


def issue_forged_verdict(verdict_name, window_id, config_paths=CONFIG_PATHS,
                          issued_at=62, expires_at=170, calibration_status="provisional"):
    """Directly emits a validly-signed verdict declaring `verdict_name`,
    bypassing pi/evidence entirely. Models A_data's 'compromises... the
    Trust Kernel' capability (CLAUDE.md §3): the signing key itself is
    attacker-controlled, so kernel_sig verifies even though no honest
    evidence produced this verdict. Used by Phase 5's adversarial-forcing
    experiment (the 'directly-emitted verdict including a forged Normal'
    class) and by enforcement tests that need a specific verdict zone
    without depending on EIS thresholds."""
    from trust_kernel.bands import TrustLevel
    effective = {d: TrustLevel.HIGH for d in DIMENSIONS}
    evidence_root = schema.build_evidence_root([])
    vfields = schema.build_verdict(
        window_id=window_id, evidence_root=evidence_root, effective_dims=effective,
        verdict=policy_mod.Verdict[verdict_name], policy_version="v1",
        crit_table_hash=policy_mod.crit_table_hash(config_paths["crit_table"]),
        ctpr_config_hash=ctpr_mod.ctpr_config_hash(config_paths["ctpr"]),
        roc_config_hash=roc_config_hash(config_paths["eis"]),
        claim_registry_hash=schema.claim_registry_hash(config_paths["claim_registry"]),
        key_registry_hash=schema.key_registry_hash(config_paths["key_registry"]),
        calibration_status=calibration_status, issued_at=issued_at, expires_at=expires_at,
    )
    _, kernel_sk = kf.kernel_keypair()
    return schema.sign_verdict(kernel_sk, vfields)


def kernel_public_key():
    pk, _ = kf.kernel_keypair()
    return pk
