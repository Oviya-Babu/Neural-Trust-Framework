"""Streaming acquisition -> signal processing (CLAUDE.md §2, §17a, Phase 7).
Substrate only: this module does not touch trust_kernel/, enforcement/,
evidence_plane/, or observer/, and emits no evidence.

Windowing uses the dataset's own canonical trial interval (moabb's
BNCI2014_001().interval == [2, 6] seconds relative to the cue annotation),
not a hand-picked window -- one fewer hyperparameter decided by us rather
than by the dataset's own standard definition.

Filtering: 8-30 Hz band-pass (the standard mu/beta motor-imagery band used
throughout the BCI literature for this exact dataset) + 50 Hz notch (Graz
recording site, European mains frequency). These are fixed, textbook
choices, decided before looking at any accuracy number -- not tuned.
"""

import mne
import numpy as np

TMIN_S = 2.0
TMAX_S = 6.0
BANDPASS_LOW_HZ = 8.0
BANDPASS_HIGH_HZ = 30.0
NOTCH_HZ = 50.0


def build_session_arrays(session_runs: dict) -> dict:
    """session_runs: {run_name: mne.io.Raw}, as returned by MOABB for one
    subject/session (e.g. data[subject]['0train']). Concatenates runs,
    band-pass + notch filters a copy, and epochs both the raw and filtered
    signal plus the EOG channels around each trial annotation.

    Returns a dict of plain numpy arrays / lists -- the pipeline's
    observable state for this session:
      raw_epochs      (n_trials, n_eeg_channels, n_samples) -- unfiltered
      filtered_epochs (n_trials, n_eeg_channels, n_samples) -- band-pass+notch
      eog_epochs      (n_trials, n_eog_channels, n_samples)
      labels          (n_trials,) int class codes
      label_names     {code: class_name}
      eeg_ch_names, eog_ch_names, sfreq
    """
    raws = [session_runs[k].copy() for k in sorted(session_runs)]
    raw = mne.concatenate_raws(raws, verbose=False)

    eeg_picks = mne.pick_types(raw.info, eeg=True, eog=False, stim=False)
    eog_picks = mne.pick_types(raw.info, eeg=False, eog=True, stim=False)
    if len(eeg_picks) == 0:
        raise ValueError("no EEG channels found in raw data")

    events, event_id = mne.events_from_annotations(raw, verbose=False)

    raw_filtered = raw.copy().filter(
        l_freq=BANDPASS_LOW_HZ, h_freq=BANDPASS_HIGH_HZ, picks=eeg_picks, verbose=False,
    )
    raw_filtered.notch_filter(freqs=[NOTCH_HZ], picks=eeg_picks, verbose=False)

    common_kwargs = dict(
        events=events, event_id=event_id, tmin=TMIN_S, tmax=TMAX_S,
        baseline=None, preload=True, verbose=False,
    )
    epochs_raw = mne.Epochs(raw, picks=eeg_picks, **common_kwargs)
    epochs_filtered = mne.Epochs(raw_filtered, picks=eeg_picks, **common_kwargs)
    epochs_eog = mne.Epochs(raw, picks=eog_picks, **common_kwargs)

    labels = epochs_filtered.events[:, 2]
    label_names = {v: k for k, v in event_id.items()}

    return {
        "raw_epochs": epochs_raw.get_data(copy=True),
        "filtered_epochs": epochs_filtered.get_data(copy=True),
        "eog_epochs": epochs_eog.get_data(copy=True),
        "labels": labels,
        "label_names": label_names,
        "eeg_ch_names": epochs_filtered.ch_names,
        "eog_ch_names": epochs_eog.ch_names,
        "sfreq": float(raw.info["sfreq"]),
    }
