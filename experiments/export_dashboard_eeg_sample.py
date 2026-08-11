"""Exports ONE real trial's raw+filtered EEG trace and real classifier
posterior for the NTF Runtime Monitor dashboard's "live EEG" panel
(Phase E). This is a REPLAY of a real recorded trial, not live acquisition
-- this project is software-only, offline, no live BCI hardware (CLAUDE.md
§1) -- and the dashboard labels it as such rather than implying otherwise.

Real subject-1 pipeline (hash-pinned load, real Phase-7 preprocessing/
features/classifier), 4 representative motor-cortex channels (C3/Cz/C4 if
present in this montage, else the first 4 EEG channels), one real test
trial. No synthetic values.

Run with the pipeline venv:
    .venv-pipeline/bin/python -m experiments.export_dashboard_eeg_sample
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import json

from bci_pipeline import loader as bci_loader
from bci_pipeline import pipeline as bci_pipeline_mod

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
SUBJECT = 1
TRIAL_INDEX = 0
PREFERRED_CHANNELS = ["C3", "Cz", "C4", "Fz"]


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    pins = bci_loader.load_pins()
    result = bci_pipeline_mod.run_subject(SUBJECT, pins=pins)
    test = result["test"]
    label_names = result["label_names"]

    ch_names = test["arrays"]["eeg_ch_names"]
    chosen = [c for c in PREFERRED_CHANNELS if c in ch_names] or ch_names[:4]
    ch_idx = [ch_names.index(c) for c in chosen]

    raw = test["arrays"]["raw_epochs"][TRIAL_INDEX]
    filtered = test["arrays"]["filtered_epochs"][TRIAL_INDEX]
    sfreq = test["arrays"]["sfreq"]
    true_label = str(label_names[int(test["labels"][TRIAL_INDEX])])
    posterior = test["posterior"][TRIAL_INDEX].tolist()
    predicted = str(result["classes_order"][int(test["posterior"][TRIAL_INDEX].argmax())])
    classes = [str(c) for c in result["classes_order"]]

    # Downsample for embedding: every 2nd sample (still ~500 points/channel,
    # real signal shape fully preserved for a small on-screen trace).
    step = 2
    payload = {
        "subject": SUBJECT, "trial_index": TRIAL_INDEX, "sfreq": sfreq / step,
        "true_label": true_label, "predicted_label": predicted,
        "classes": classes, "posterior": posterior,
        "channels": chosen,
        "raw": {c: raw[i, ::step].round(3).tolist() for c, i in zip(chosen, ch_idx)},
        "filtered": {c: filtered[i, ::step].round(3).tolist() for c, i in zip(chosen, ch_idx)},
        "note": "REAL recorded trial, replayed for display -- this project is software-only offline "
                "(CLAUDE.md §1), there is no live acquisition to show.",
    }
    out_path = ARTIFACTS_DIR / "dashboard_eeg_sample.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {out_path} ({len(chosen)} channels x {len(payload['raw'][chosen[0]])} samples)")


if __name__ == "__main__":
    main()
