"""Feature extraction: Riemannian tangent-space mapping (CLAUDE.md §2,
§17a, Phase 7). Substrate only.

Baseline choice (pre-registered here, before this driver was re-run against
real data): trial spatial-covariance matrices projected to the tangent
space at the Riemannian mean, following Barachant, Bonnet, Congedo &
Jutten (2013), "Classification of covariance matrices using a Riemannian-
based kernel for BCI applications", Neurocomputing 112. This is the
standard MOABB reference pipeline for BCI Competition IV 2a cross-session
decoding (Jayaram & Barachant, 2018, "MOABB: trustworthy algorithm
benchmarking for BCIs", J. Neural Eng. 15(6); "Tangent Space LR" in the
MOABB pipeline zoo).

Justification is cross-session robustness, not accuracy: the covariance/
tangent-space representation is substantially more robust to session-to-
session nonstationarity (electrode impedance drift, day-to-day EEG
variability) than a CSP+LDA spatial filter fit on one session and applied
to another, which is exactly the property this substrate's cross-session
protocol (§17a) needs -- this dataset was picked *for* its cross-session
structure. That is a correctness argument about the evaluation protocol,
decided independent of any observed number, and not revisited after seeing
one (§17a: no tuning toward a target).

estimator="oas" (Oracle Approximating Shrinkage, Chen, Wiesel, Eldar &
Hero, 2010) is the standard well-conditioned covariance estimator for this
regime (22 channels, ~1000 samples per trial) -- fixed, not tuned.
"""

from pyriemann.estimation import Covariances
from pyriemann.tangentspace import TangentSpace

COVARIANCE_ESTIMATOR = "oas"


def fit_features(filtered_epochs_train):
    """Fits the covariance estimator and tangent-space mapping on the
    training session only. Returns ((cov, tangent), features_train)."""
    cov = Covariances(estimator=COVARIANCE_ESTIMATOR)
    tangent = TangentSpace(metric="riemann")
    cov_train = cov.fit_transform(filtered_epochs_train)
    features_train = tangent.fit_transform(cov_train)
    return (cov, tangent), features_train


def transform_features(fitted, filtered_epochs):
    """Transforms (never fits) -- for the held-out session, per the
    cross-session protocol (§17a)."""
    cov, tangent = fitted
    cov_x = cov.transform(filtered_epochs)
    return tangent.transform(cov_x)
