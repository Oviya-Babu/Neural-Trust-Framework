"""Signal evidence producer (CLAUDE.md §2, §10, Phase 8 Step 2).

Grounded, REAL measurement source (config/claim_registry.json's
signal.provisional_v0: measurement_source=REAL, host_independence=SAME_HOST,
forgeable_under_A_code=TRUE -- runs on the host, so honest-evidence-
conditional under Position A like everything else in V1).

Runtime component: a per-window spectral analysis step reading the raw
(unfiltered) Phase-7 epoch for one trial -- deliberately the RAW trace, not
the filtered one: the band-pass + notch filter (bci_pipeline/preprocessing.py)
already removes exactly the contamination this producer needs to measure
the presence of, so measuring after filtering would silently show a clean
signal regardless of what arrived at the sensor.

Runtime measurement: Welch power spectral density (scipy.signal.welch),
averaged across EEG channels, evaluated over three bands:
  - mu/beta power (8-30 Hz): the motor-imagery signal band this whole
    pipeline exists to decode (bci_pipeline/preprocessing.py's own filter
    band, §17a).
  - broadband power (1-45 Hz): the usable EEG range excluding DC drift and
    the classifier's own anti-alias/notch neighbourhood.
  - line-noise power (48-52 Hz): centred on mains frequency (50 Hz at the
    Graz recording site, matching preprocessing.py's NOTCH_HZ) -- power
    concentrated here on the RAW trace is environmental/electrical
    contamination the filter has to remove, not signal.

Mathematical calculation:
  snr_ratio = mu_beta_power / max(broadband_power - mu_beta_power, EPS)
  snr_db = 10 * log10(snr_ratio + EPS)
  line_noise_fraction = line_power / max(broadband_power, EPS)
  raw_measurement = clip(
      round(snr_db * SNR_SCALE - line_noise_fraction * LINE_NOISE_PENALTY_SCALE),
      RAW_FLOOR, RAW_CEIL,
  )
Both terms move the same direction (higher SNR is better, higher line
contamination is worse), combined additively into one composite score
because config/claim_registry.json registers exactly one Signal claim type
for V1 (signal.provisional_v0) -- three real, independently-attack-relevant
measurements feeding one raw_measurement, not three separate claims (§2:
claim types emerge from what is measurable and registered, not invented
ahead of registration).

measurement units: dimensionless fixed-point composite score, scale pinned
by SNR_SCALE/LINE_NOISE_PENALTY_SCALE below.
claim type: signal.provisional_v0. trust dimension: Signal.
timestamp/provenance: caller-supplied window_id/claimed_at (this module
reads no clock).
expected polarity: +1 (higher raw = more trustworthy, per config/eis.v0.json).
window binding: one measurement per window, over that window's own trial
epoch -- no cross-window state.
smoothing behaviour: none. A single trial's spectral content is itself the
signal; averaging across trials would hide a one-window injection.
attacks influencing this measurement: signal injection and adversarial EEG
(§3) that concentrate energy outside the mu/beta band or introduce
broadband noise, lowering snr_db; communication tampering that corrupts
raw samples (electrical/injected noise raises line_noise_fraction);
firmware modification that alters ADC/amplifier behaviour (shows up as
broadband noise or line contamination). NOT sensitive to attacks that
preserve the raw spectral envelope while altering only downstream
interpretation (e.g. model replacement) -- that is Model's job, not
Signal's; this producer never reads the classifier's output.

calibration_status: this module computes a real measurement from real data,
but config/eis.v0.json's ROC/threshold config for signal.provisional_v0 is
still the Phase 2 placeholder curve (CLAUDE.md §14: "Phases 1-9 run under
calibration_status: provisional... Phase 9's measured-ROC integration"
flips it) -- measured ROC integration is explicitly Phase 9, not this step.

No confidence is computed here (§2): this is a raw measurement only.
"""

import numpy as np
from scipy.signal import welch

from trust_kernel import schema

SIGNAL_CLAIM_TYPE = "signal.provisional_v0"
SIGNAL_SOURCE_ID = "signal_sensor_v0"
SIGNAL_BOUNDARY = "TB2"

MU_BETA_BAND_HZ = (8.0, 30.0)
BROADBAND_HZ = (1.0, 45.0)
LINE_NOISE_BAND_HZ = (48.0, 52.0)

SNR_SCALE = 4  # raw units per dB of in-band SNR
LINE_NOISE_PENALTY_SCALE = 300  # raw units per unit line_noise_fraction (0..1)
RAW_FLOOR = -100
RAW_CEIL = 100
EPS = 1e-15


def _band_power(freqs: np.ndarray, psd: np.ndarray, band_hz: tuple) -> float:
    lo, hi = band_hz
    mask = (freqs >= lo) & (freqs <= hi)
    if not np.any(mask):
        return 0.0
    return float(np.trapezoid(psd[mask], freqs[mask]))


def measure_signal_quality(raw_epoch: np.ndarray, sfreq: float) -> int:
    """raw_epoch: (n_channels, n_samples) unfiltered EEG for one trial.
    Returns the fixed-point composite score described in the module
    docstring."""
    nperseg = min(raw_epoch.shape[1], int(sfreq * 2))  # 2 s segments, capped by trial length
    freqs, psd = welch(raw_epoch, fs=sfreq, nperseg=nperseg, axis=-1)
    psd_mean = psd.mean(axis=0)  # average across channels

    mu_beta_power = _band_power(freqs, psd_mean, MU_BETA_BAND_HZ)
    broadband_power = _band_power(freqs, psd_mean, BROADBAND_HZ)
    line_power = _band_power(freqs, psd_mean, LINE_NOISE_BAND_HZ)

    snr_ratio = mu_beta_power / max(broadband_power - mu_beta_power, EPS)
    snr_db = 10.0 * np.log10(snr_ratio + EPS)
    line_noise_fraction = line_power / max(broadband_power, EPS)

    raw = snr_db * SNR_SCALE - line_noise_fraction * LINE_NOISE_PENALTY_SCALE
    return int(np.clip(round(raw), RAW_FLOOR, RAW_CEIL))


class SignalSensor:
    def __init__(self, secret_key: bytes, key_id: str = SIGNAL_SOURCE_ID, source_id: str = SIGNAL_SOURCE_ID):
        self._secret_key = secret_key
        self.key_id = key_id
        self.source_id = source_id

    def build_statement(self, *, raw_epoch: np.ndarray, sfreq: float, window_id: int, claimed_at: int) -> dict:
        raw = measure_signal_quality(raw_epoch, sfreq)
        fields = schema.build_statement(
            key_id=self.key_id, source_id=self.source_id, boundary=SIGNAL_BOUNDARY,
            claim_type=SIGNAL_CLAIM_TYPE, raw_measurement=raw,
            window_id=window_id, claimed_at=claimed_at,
        )
        return schema.sign_statement(self._secret_key, fields)
