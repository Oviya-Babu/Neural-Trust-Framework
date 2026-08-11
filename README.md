# NTF — Neural Trust Framework

PhD research prototype: a trust-reasoning security architecture for
Brain–Computer Interface cyber-physical systems.

## Layout

```
trust_kernel/     evidence_plane/   enforcement/    sensors/    observer/
bci_pipeline/     attack_framework/ latency/        event_model/
sba_validation/   roc_estimability/
tests*/           harnesses/        experiments/    config/
artifacts/        provenance/       docs/
```

Six pluggable evidence sensors, a pure jailed trust kernel, a dumb
capability-gated enforcer, for the full architecture
and layout rationale.

## Dependency boundaries (three environments, deliberately separate)

| What | Env | Why separate |
|---|---|---|
| Pure core (`trust_kernel/`, `evidence_plane/`, `enforcement/`, `observer/`, `event_model/`, `sba_validation/`, `roc_estimability/`, `latency/`, `attack_framework/`) | system `python3`, **zero deps** | Artifact reproduction must be `python3 -m unittest discover -s tests` with nothing to resolve (CLAUDE.md §11). |
| `bci_pipeline/`, `sensors/`, real-data `experiments/*` | `.venv-pipeline` | Real EEG signal processing genuinely needs numpy/scipy/mne/moabb/pyriemann/cryptography. |
| `experiments/generate_figures.py` | `.venv-figures` | Needs only matplotlib, over already-computed JSON — no reason to inherit the pipeline venv's heavier deps. |
| `experiments/generate_dashboard.py`, `experiments/run_all_mutation_harnesses.py` | system `python3` | Pure aggregation over already-computed JSON, or subprocess orchestration — no special deps either. |

```bash
python3 -m venv .venv-pipeline && .venv-pipeline/bin/pip install -r requirements-bci_pipeline.txt
python3 -m venv .venv-figures  && .venv-figures/bin/pip install -r requirements-figures.txt
```

## One-command reproduction, per artifact

```bash
# Pure-core test suites (no venv needed)
python3 -m unittest discover -s tests
python3 -m unittest discover -s tests_event_model
python3 -m unittest discover -s tests_sba
python3 -m unittest discover -s tests_roc_estimability
python3 -m unittest discover -s tests_latency
python3 -m unittest discover -s tests_attack_framework
.venv-pipeline/bin/python -m unittest discover -s tests_sensors
.venv-pipeline/bin/python -m unittest discover -s tests_bci_pipeline

# Mutation testing (all 8 harnesses, fresh, writes artifacts/mutation_summary.json)
python3 -m experiments.run_all_mutation_harnesses

# Phase experiments, in dependency order (each writes its own artifacts/*.json + provenance/*_manifest.json)
python3 -m experiments.phase2_kernel_core
python3 -m experiments.phase3_t4_admission
python3 -m experiments.phase4_evidence_log
python3 -m experiments.phase5_enforcement
python3 -m experiments.phase6_observer
.venv-pipeline/bin/python -m experiments.phase7_bci_pipeline
.venv-pipeline/bin/python -m experiments.phase8_evidence_producers
.venv-pipeline/bin/python -m experiments.event_model_investigation
.venv-pipeline/bin/python -m experiments.phase8_5_sba_validation
.venv-pipeline/bin/python -m experiments.roc_estimability_diagnostic
.venv-pipeline/bin/python -m experiments.phase9_measured_roc
.venv-pipeline/bin/python -m experiments.phase10_latency_evaluation
.venv-pipeline/bin/python -m experiments.phase11_attack_framework
.venv-pipeline/bin/python -m experiments.phase12_fault_injection

# Figures/tables (reads already-computed JSON only, produces artifacts/figures/*.png/.svg/.csv)
.venv-figures/bin/python -m experiments.generate_figures

# Dashboard (reads already-computed JSON only, produces artifacts/ntf_runtime_monitor.html)
.venv-pipeline/bin/python -m experiments.export_dashboard_eeg_sample   # real EEG sample for the dashboard's replay panel
python3 -m experiments.generate_dashboard
```

No figure, table, or dashboard value is hand-typed — every one traces to a
`artifacts/*.json` produced by a driver above.

## Dataset

BCI Competition IV 2a via MOABB, hash-pinned (`config/dataset_pins.json`):
resolved download URL and per-file SHA-256 for all 9 subjects × 2 sessions,
verified on every load, fail-closed on mismatch (`bci_pipeline/loader.py`).
"MOABB default" is never treated as a pin.

## Reproducibility discipline

Every experiment driver emits a manifest (`provenance/*_manifest.json`):
config hashes, git state, hardware/OS, seeds, timestamps.
Corrections to an already-reported result are never silent reruns: they are
disclosed post-hoc, with before/after content hashes recorded in the
manifest (see `provenance/phase9_measured_roc_manifest.json` and
`provenance/phase11_attack_framework_manifest.json` for two real examples).

