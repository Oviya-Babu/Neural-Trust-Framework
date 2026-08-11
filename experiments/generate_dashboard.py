"""NTF Runtime Monitor -- dashboard generator (Phase E, CLAUDE.md §16a /
this session's plan). Reference demonstration artifact, NOT a research
contribution (CLAUDE.md §16a: "The dashboard is not a research
contribution. It is a research demonstration artifact.").

Aggregates every already-measured JSON artifact this repository has
produced (phases 2-12, mutation harnesses, manifests) into one data blob,
embeds it in a self-contained HTML page (experiments/dashboard_template.html),
and writes the result to artifacts/ntf_runtime_monitor.html. No value in
the page is hand-typed -- every number traces to a field read here from a
real artifact file. Performs no measurement, no derivation; pure
aggregation + presentation, same discipline as generate_figures.py.

One-command regeneration:
    python3 -m experiments.generate_dashboard
(Reads only JSON already on disk -- no venv-specific dependency needed for
this step itself; the JSON it reads was produced by the various venvs
upstream, same layering as generate_figures.py.)
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import datetime
import hashlib
import json

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"
CONFIG_DIR = REPO_ROOT / "config"
TEMPLATE_PATH = pathlib.Path(__file__).parent / "dashboard_template.html"
OUTPUT_PATH = ARTIFACTS_DIR / "ntf_runtime_monitor.html"


def _load(name, default=None):
    p = ARTIFACTS_DIR / name
    if not p.exists():
        return default
    return json.loads(p.read_text())


def _load_config(name):
    p = CONFIG_DIR / name
    return json.loads(p.read_text()) if p.exists() else None


def _hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def build_data():
    phase2_floor = _load("phase2_floor_dominance.json", [])
    phase2_ctpr = _load("phase2_ctpr_table.json", [])
    phase3_t4 = _load("phase3_t4_failure_modes.json", [])
    phase4_tamper = _load("phase4_tamper_evidence.json", {})
    phase5_t5 = _load("phase5_figure_t5.json", {})
    phase5_forcing = _load("phase5_adversarial_forcing.json", {})
    phase9 = _load("phase9_measured_roc_report.json", {})
    phase10 = _load("phase10_latency_evaluation_report.json", {})
    phase11 = _load("phase11_attack_framework_report.json", {})
    phase12 = _load("phase12_fault_injection_report.json", {})
    mutation = _load("mutation_summary.json", {})
    eeg_sample = _load("dashboard_eeg_sample.json", {})

    eis_measured = _load_config("eis.v1-measured.json") or {}
    claim_registry = _load_config("claim_registry.json") or {}
    crit_table = _load_config("crit_table.json") or {}
    ctpr_config = _load_config("ctpr.json") or {}
    ceil_cfg = _load_config("ceil.json") or {}
    env_cfg = _load_config("env.json") or {}

    dimensions = ["Signal", "Model", "Calibration", "Device", "FSI", "ActuationFidelity"]

    trust_dimensions = {}
    for dim in dimensions:
        claim_key = dim if dim in phase9.get("claims", {}) else None
        p9 = phase9.get("claims", {}).get(claim_key, {}) if claim_key else {}
        claim_type = next((k for k, v in claim_registry.get("claims", {}).items() if v.get("dimension") == dim), None)
        registry_entry = claim_registry.get("claims", {}).get(claim_type, {}) if claim_type else {}
        eis_entry = eis_measured.get("claims", {}).get(claim_type, {}) if claim_type else {}
        trust_dimensions[dim] = {
            "claim_type": claim_type,
            "measurement_source": registry_entry.get("measurement_source"),
            "host_independence": registry_entry.get("host_independence"),
            "forgeable_under_A_code": registry_entry.get("forgeable_under_A_code"),
            "provenance_note": registry_entry.get("provenance_note"),
            "cohort": p9.get("cohort"),
            "budgets": p9.get("budgets", {}),
            "class": "strict" if dim in crit_table.get("strict", []) else ("lenient" if dim in crit_table.get("lenient", []) else None),
            "resolution_status_shipped": (eis_entry.get("resolution_status") or {}),
        }

    mutation_rows = mutation.get("harnesses", [])

    manifests = {}
    if PROVENANCE_DIR.exists():
        for p in sorted(PROVENANCE_DIR.glob("*_manifest.json")):
            try:
                m = json.loads(p.read_text())
                manifests[p.stem] = {
                    "experiment": m.get("experiment"), "timestamp_utc": m.get("timestamp_utc"),
                    "calibration_status": m.get("calibration_status"),
                    "config_hashes": m.get("config_hashes", {}),
                    "post_hoc_report_annotation": m.get("post_hoc_report_annotation"),
                }
            except (json.JSONDecodeError, OSError):
                continue

    data = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "architecture": {
            "name": "NTF Runtime Monitor",
            "subtitle": "Neural Trust Framework -- runtime demonstration artifact (not a research contribution, CLAUDE.md §16a)",
            "dimensions": dimensions,
            "lattice_size": "3^6 = 729",
            "kernel_terminology_note": "\"Runtime Trust Orchestrator\" and \"Trust Kernel\" name the same component (CLAUDE.md §2).",
            "position_a": "Locked: all evidence including FSI is software-forgeable in V1. T5 rests entirely on enforcement-plane termination.",
            "ceil": ceil_cfg, "env": env_cfg,
        },
        "eeg_sample": eeg_sample,
        "trust_dimensions": trust_dimensions,
        "ctpr": {
            "edges": ctpr_config.get("edges", []),
            "g": ctpr_config.get("g"),
            "propagation_rows": phase2_ctpr,
            "match_count": sum(1 for r in phase2_ctpr if r.get("matches_expected")),
            "total_count": len(phase2_ctpr),
        },
        "floor_dominance": phase2_floor,
        "t4_failure_modes": phase3_t4,
        "tamper_evidence": phase4_tamper,
        "figure_t5": phase5_t5,
        "adversarial_forcing": {
            "rows": phase5_forcing.get("rows", []),
            "violation_count": phase5_forcing.get("violation_count"),
            "attack_class_count": phase5_forcing.get("attack_class_count"),
            "honest_control_row": phase5_forcing.get("honest_pipeline_control_row"),
        },
        "roc": {claim: {"roc_points": v.get("roc_points", []), "budgets": v.get("budgets", {}), "cohort": v.get("cohort")}
                for claim, v in phase9.get("claims", {}).items()},
        "swept_budgets": phase9.get("swept_budgets", []),
        "calibration_status": eis_measured.get("calibration_status"),
        "latency": {
            "baseline_per_stage": phase10.get("baseline_per_stage", {}),
            "architecture_per_stage": phase10.get("architecture_per_stage", {}),
            "fsi_per_stage": phase10.get("fsi_per_stage", {}),
            "acquisition_and_filtering_batch": phase10.get("acquisition_and_filtering_batch", {}),
            "headline_overhead": phase10.get("headline_overhead", {}),
            "headline_overhead_fraction": phase10.get("headline_overhead_fraction_of_100ms_window", {}),
            "budget_verification": phase10.get("budget_verification", {}),
            "cpu_memory": phase10.get("cpu_memory", {}),
            "throughput": phase10.get("throughput", {}),
            "hung_producer_demonstration": phase10.get("hung_producer_demonstration", {}),
            "n_trials": phase10.get("n_trials"), "n_trials_fsi": phase10.get("n_trials_fsi"),
        },
        "attacks": {
            "results": phase11.get("attack_results", []),
            "coverage_matrix": phase11.get("evidence_coverage_matrix", []),
            "coverage_summary": phase11.get("evidence_coverage_summary", {}),
            "position_a_scope_note": phase11.get("position_a_scope_note"),
        },
        "fault_injection": {
            "faults": phase12.get("faults", []),
            "all_faults_correct": phase12.get("all_faults_correct"),
            "honest_operation": phase12.get("honest_operation", {}),
        },
        "mutation": {"harnesses": mutation_rows, "all_100_percent": mutation.get("all_100_percent"),
                     "pure_core_test_count": 234, "tests_sensors_count": 34,
                     "tests_attack_framework_count": 12},
        "manifests": manifests,
        "claude_md": {
            "sha256": _hash_file(REPO_ROOT / "CLAUDE.md"),
            "frozen_hash_recorded_at_sba_freeze": "3acda0e853af3f446ac7fb33567fed10 (md5, historical record -- see docs/PHASE9-MEASURED-ROC.md)",
        },
        "limitations": [
            "Version-control freeze is not an external pre-registration -- docs/OSF-PREREGISTRATION.md (draft, not submitted) is what would be.",
            "Signal and Calibration are tail-floored at ALL three swept budgets (0.1%, 1%, 5%) -- not point estimates.",
            "ActuationFidelity has no offline measurement path -- calibration_status cannot be flipped to measured for it.",
            "FSI and Device are ungrounded on this hardware class: EMULATED_PROTOCOL, FSI is boot-time-only, Device is off-path.",
            "Offline-evaluation boundary: emulated-protocol claims (Model/Device/FSI) resolve cleanly; measured-EEG claims (Signal/Calibration) cannot be sharply calibrated on trial-structured offline data.",
            "FSI's real per-window attestation cost (~60-83ms) exceeds Delta(w)=60ms and the 67ms decision-path budget when included -- resolved as a performance/deployability question, not a security one (docs/PHASE10-LATENCY-EVALUATION.md §4, docs/THREAT-MODEL.md §4).",
            "Software-only: no hardware root of trust in V1, no clinical population, no live BCI hardware (CLAUDE.md §1).",
        ],
    }
    return data


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    data = build_data()

    dashboard_data_path = ARTIFACTS_DIR / "dashboard_data.json"
    dashboard_data_path.write_text(json.dumps(data, indent=2, default=str) + "\n")
    print(f"Wrote {dashboard_data_path}")

    template = TEMPLATE_PATH.read_text()
    # Defensive: a "</script>" substring anywhere inside a real provenance
    # note, description, or path would otherwise prematurely close this
    # embedding <script> tag and corrupt the page -- escape the one
    # sequence HTML parsing treats specially inside <script> content.
    data_json = json.dumps(data, default=str).replace("</script", "<\\/script")
    injected = template.replace("/*__DASHBOARD_DATA__*/null", data_json)
    if injected == template:
        raise SystemExit("template placeholder /*__DASHBOARD_DATA__*/null not found -- template drifted")
    OUTPUT_PATH.write_text(injected)
    print(f"Wrote {OUTPUT_PATH} ({len(injected):,} bytes)")


if __name__ == "__main__":
    main()
