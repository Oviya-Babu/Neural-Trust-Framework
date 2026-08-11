"""Artifact detection (CLAUDE.md §2, §17a, Phase 7). Substrate only.

Runtime measurement: peak-to-peak EOG amplitude, computed within a short
sliding window over each trial epoch (not over the whole trial). EOG
channels are physically dedicated to eye-movement/blink pickup, so a large
deflection there is a genuine, independent indicator of contamination -- not
a property of the same signal the classifier consumes (the classifier's
features come from EEG channels only, never EOG).

Temporal scale (correctness fix, not an accuracy-driven retune): a single
eye blink has a stereotyped duration of roughly 200-400 ms (Volkmann, Riggs
& Moore, 1980, "Eyeblinks and visual suppression", Vision Research 20(9)).
Computing peak-to-peak amplitude over the *entire* 4 s motor-imagery trial
(this dataset's own MI event is a sustained 4 s event, §17a) conflates a
short, genuine transient with any accumulated baseline drift across the
whole window -- the wrong temporal scale flags nearly every trial regardless
of whether a blink actually occurred in it. Artifact-rejection pipelines
therefore apply the amplitude criterion within a short window sized to the
physiological event, e.g. the moving-window peak-to-peak method surveyed in
Fatourechi, Bashashati, Ward & Birch (2007), "EMG and EOG artifacts in
brain-computer interface systems: A survey", Clinical Neurophysiology
118(3). This module was changed to that shape for that reason, decided
before re-running the pipeline, not because of any observed accuracy delta
(§17a: never justify a measurement-definition change by its effect on the
reported number).

Threshold: unchanged at 100 microvolts peak-to-peak, the standard EOG-
artifact amplitude criterion used throughout the EEG/BCI literature
(Semlitsch, Anderer, Schuster & Saletu, 1986, "A solution for reliable and
valid reduction of ocular artifacts, applied to the P300 ERP",
Psychophysiology 23(6)) -- only the window over which it is applied changed.
"""

import numpy as np

EOG_ARTIFACT_THRESHOLD_V = 100e-6  # 100 uV; MNE stores signal amplitude in volts
EOG_WINDOW_MS = 300.0  # within the 200-400 ms single-blink duration range
EOG_WINDOW_STEP_MS = 100.0  # overlapping slide, so no blink falls between windows


def detect_eog_artifacts(
    eog_epochs: np.ndarray,
    sfreq: float,
    threshold_v: float = EOG_ARTIFACT_THRESHOLD_V,
    window_ms: float = EOG_WINDOW_MS,
    step_ms: float = EOG_WINDOW_STEP_MS,
) -> dict:
    """eog_epochs: (n_trials, n_eog_channels, n_samples). sfreq: Hz.

    Returns {flags: bool (n_trials,), scores: float (n_trials,)} where
    scores[i] is the largest peak-to-peak amplitude across EOG channels
    AND across sliding windows for trial i, and flags[i] = scores[i] >
    threshold_v -- i.e. a trial is flagged if any short window within it
    exceeds the amplitude criterion, not if the whole-trial span does.
    """
    n_trials, n_channels, n_samples = eog_epochs.shape
    window_samples = max(1, int(round(window_ms / 1000.0 * sfreq)))
    step_samples = max(1, int(round(step_ms / 1000.0 * sfreq)))

    starts = list(range(0, max(1, n_samples - window_samples + 1), step_samples))
    if not starts:
        starts = [0]
        window_samples = n_samples

    worst = np.zeros(n_trials)
    for start in starts:
        window = eog_epochs[:, :, start:start + window_samples]
        ptp = window.max(axis=2) - window.min(axis=2)  # (n_trials, n_eog_channels)
        worst = np.maximum(worst, ptp.max(axis=1))

    flags = worst > threshold_v
    return {
        "flags": flags,
        "scores": worst,
        "threshold_v": threshold_v,
        "window_ms": window_ms,
        "step_ms": step_ms,
    }
