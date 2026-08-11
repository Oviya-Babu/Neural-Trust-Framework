"""Continuous (not epoched) real-signal sliding-window stream for the
event-model investigation (prerequisite to Phase 9; CLAUDE.md not
modified by this work). Reuses bci_pipeline.loader (hash-verified real
data access), bci_pipeline.preprocessing's filter constants,
bci_pipeline.pipeline.run_subject (for the real fitted tangent-space
transform + enrollment stats), bci_pipeline.features.transform_features,
and sensors.signal_sensor.measure_signal_quality /
sensors.calibration_sensor.measure_calibration_drift / compute_enrollment_stats
DIRECTLY -- none of bci_pipeline/ or sensors/ is modified or reimplemented
here.

Why this module exists rather than reusing bci_pipeline/preprocessing.py
as-is: Phase 7's substrate is epoch-based (one 4s motor-imagery trial per
epoch, cued by an event marker) -- it has no notion of a continuous
100ms-window stream across a whole session (CLAUDE.md 7's window period),
which this investigation needs to measure temporal dependence between
consecutive windows, including inter-trial periods. This module builds
that stream by keeping the continuous concatenated Raw signal (instead of
epoching it at fixed trial boundaries) and sliding a window across it.

Analysis-window vs. hop distinction: each emitted "window" corresponds to
one 100ms hop (CLAUDE.md 7's real window period), but the underlying
spectral/covariance measurement needs more than 100ms of context to be
numerically meaningful (100ms = 25 samples at 250Hz is too short for a
stable Welch PSD or covariance estimate) -- so each hop's measurement is
computed over a longer ANALYSIS window (default 1.0s) ending at that hop,
a standard sliding-window-with-hop streaming-DSP pattern. This is a new
methodological choice for this streaming investigation, not something
CLAUDE.md or Phase 7/8 specifies (Phase 7/8's epoch-based substrate never
needed it) -- flagged here rather than silently assumed uncontroversial.
"""

import mne
import numpy as np

from bci_pipeline import features as bci_features
from bci_pipeline import loader as bci_loader
from bci_pipeline import pipeline as bci_pipeline_mod
from bci_pipeline import preprocessing as bci_preprocessing
from sensors import calibration_sensor, signal_sensor

DEFAULT_ANALYSIS_WINDOW_S = 1.0
DEFAULT_HOP_S = 0.100  # CLAUDE.md 7: T = 100ms


def load_continuous_raw(subject: int, session_key: str, cache_dir=None, pins: dict = None):
    """Returns (raw, raw_filtered, eeg_picks, sfreq, verified_files) for
    the FULL continuous recording of one session (all runs concatenated)
    -- NOT epoched. Applies the same band-pass + notch filter as
    bci_pipeline.preprocessing.build_session_arrays, using that module's
    own constants directly (not duplicated values)."""
    cache_dir = cache_dir or bci_loader.DEFAULT_CACHE_DIR
    mne_data, verified_files = bci_loader.load_subject_data(subject, cache_dir=cache_dir, pins=pins)
    session_runs = mne_data[session_key]
    raws = [session_runs[k].copy() for k in sorted(session_runs)]
    raw = mne.concatenate_raws(raws, verbose=False)

    eeg_picks = mne.pick_types(raw.info, eeg=True, eog=False, stim=False)
    raw_filtered = raw.copy().filter(
        l_freq=bci_preprocessing.BANDPASS_LOW_HZ, h_freq=bci_preprocessing.BANDPASS_HIGH_HZ,
        picks=eeg_picks, verbose=False,
    )
    raw_filtered.notch_filter(freqs=[bci_preprocessing.NOTCH_HZ], picks=eeg_picks, verbose=False)

    return raw, raw_filtered, eeg_picks, float(raw.info["sfreq"]), verified_files


def sliding_window_starts(n_samples: int, sfreq: float, analysis_window_s: float, hop_s: float):
    window_samples = int(round(analysis_window_s * sfreq))
    hop_samples = int(round(hop_s * sfreq))
    if window_samples <= 0 or hop_samples <= 0:
        raise ValueError("analysis_window_s and hop_s must be positive relative to sfreq")
    starts = list(range(0, max(0, n_samples - window_samples) + 1, hop_samples))
    return starts, window_samples


def compute_signal_and_calibration_stream(subject: int, pins: dict = None,
                                           analysis_window_s: float = DEFAULT_ANALYSIS_WINDOW_S,
                                           hop_s: float = DEFAULT_HOP_S,
                                           cache_dir=None):
    """Runs the real bci_pipeline.pipeline.run_subject once to obtain the
    fitted tangent-space transform + enrollment stats from session T
    (train) -- exactly what sensors/calibration_sensor.py's Calibration
    claim compares against (Phase 8) -- then slides a window across
    session E's (test) CONTINUOUS raw+filtered signal, calling the real
    sensors.signal_sensor.measure_signal_quality and
    sensors.calibration_sensor.measure_calibration_drift per hop,
    unmodified.

    Session E (test) is used as "the honest operation period" being
    monitored, matching how Calibration's drift claim is framed
    throughout Phase 7/8 (session T = enrollment, session E = deployed
    operation). Model, Device, FSI, ActuationFidelity are NOT computed
    here: under honest, no-attack, single-session operation with no live
    enforcement loop, those four are discrete pass/fail integrity checks
    (Ed25519 verify, DTLS handshake, TPM quote, actuator feedback) with no
    continuously-varying real-valued measurement defined for streaming
    100ms cadence in the current architecture -- an explicit, stated scope
    limitation of this investigation (see the Phase-8.6-style report),
    not a claim that they are perfectly reliable.
    """
    result = bci_pipeline_mod.run_subject(subject, pins=pins)
    fitted_features = result["fitted_features"]
    enrollment_stats = calibration_sensor.compute_enrollment_stats(result["train"]["features"])

    raw, raw_filtered, eeg_picks, sfreq, verified_files = load_continuous_raw(
        subject, "1test", cache_dir=cache_dir, pins=pins,
    )
    raw_eeg = raw.get_data(picks=eeg_picks)
    filtered_eeg = raw_filtered.get_data(picks=eeg_picks)

    starts, window_samples = sliding_window_starts(raw_eeg.shape[1], sfreq, analysis_window_s, hop_s)

    signal_raw = np.empty(len(starts), dtype=np.int64)
    calibration_raw = np.empty(len(starts), dtype=np.int64)
    for i, s in enumerate(starts):
        raw_slice = raw_eeg[:, s:s + window_samples]
        filtered_slice = filtered_eeg[:, s:s + window_samples]

        signal_raw[i] = signal_sensor.measure_signal_quality(raw_slice, sfreq)

        feat = bci_features.transform_features(fitted_features, filtered_slice[np.newaxis, :, :])[0]
        calibration_raw[i] = calibration_sensor.measure_calibration_drift(feat, enrollment_stats)

    return {
        "subject": subject, "sfreq": sfreq, "n_windows": len(starts),
        "hop_s": hop_s, "analysis_window_s": analysis_window_s,
        "signal_raw": signal_raw, "calibration_raw": calibration_raw,
        "session_duration_s": raw_eeg.shape[1] / sfreq,
        "verified_files": {k: {"sha256": v["sha256"], "key": v["key"]} for k, v in verified_files.items()},
    }
