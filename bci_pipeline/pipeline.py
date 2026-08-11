"""Phase 7 pipeline orchestrator (CLAUDE.md §2, §17a). Substrate only: no
evidence producers, no security instrumentation, no trust_kernel/
enforcement/evidence_plane/observer calls anywhere in this module or the
stages it composes.

Stages, in order (§2's Software BCI Pipeline, through "Predicted Intent"):
EEG Dataset (loader) -> Streaming Acquisition + Signal Processing
(preprocessing) -> Artifact Detection (artifacts) -> Feature Extraction
(features, Riemannian tangent-space) -> Classification (classifier,
logistic regression) -> Predicted Intent.

Cross-session protocol (§17a): the covariance estimator, tangent-space
mapping, and classifier are all fit on session '0train' only; session
'1test' is only ever transformed/predicted, never fit on -- the standard
train/eval separation that makes this dataset's cross-session structure
meaningful.
"""

import numpy as np

from bci_pipeline import artifacts, classifier, features, loader, preprocessing


def _remap_labels_to_train_codes(test_labels, test_label_names, train_label_names):
    """events_from_annotations assigns integer codes by sorting annotation
    description strings, which is deterministic and should already agree
    between sessions recorded with the same four class names -- this
    remap is a safety net, not an expected no-op, and is asserted to be a
    true no-op below (§ scope: don't silently paper over a real mismatch)."""
    if test_label_names == train_label_names:
        return test_labels
    name_to_train_code = {name: code for code, name in train_label_names.items()}
    test_code_to_name = test_label_names
    remapped = np.array([name_to_train_code[test_code_to_name[c]] for c in test_labels])
    return remapped


def run_subject(subject: int, cache_dir=None, pins: dict = None) -> dict:
    """Runs the full Phase 7 substrate pipeline for one subject: load
    (hash-verified) -> filter -> epoch -> detect artifacts -> CSP features
    -> LDA -> predicted intent, on both sessions, cross-session (fit on
    train, evaluate on test).
    """
    cache_dir = cache_dir or loader.DEFAULT_CACHE_DIR
    mne_data, verified_files = loader.load_subject_data(subject, cache_dir=cache_dir, pins=pins)

    session_names = list(mne_data.keys())
    train_key = next(s for s in session_names if "train" in s)
    test_key = next(s for s in session_names if "test" in s)

    train_arrays = preprocessing.build_session_arrays(mne_data[train_key])
    test_arrays = preprocessing.build_session_arrays(mne_data[test_key])

    test_labels = _remap_labels_to_train_codes(
        test_arrays["labels"], test_arrays["label_names"], train_arrays["label_names"]
    )
    assert np.array_equal(test_labels, test_arrays["labels"]), (
        "test-session label codes disagree with train-session label codes -- "
        "events_from_annotations produced inconsistent class->code mappings "
        "across sessions, which should not happen for this dataset"
    )

    train_af = artifacts.detect_eog_artifacts(train_arrays["eog_epochs"], sfreq=train_arrays["sfreq"])
    test_af = artifacts.detect_eog_artifacts(test_arrays["eog_epochs"], sfreq=test_arrays["sfreq"])

    fitted_features, train_features = features.fit_features(train_arrays["filtered_epochs"])
    test_features = features.transform_features(fitted_features, test_arrays["filtered_epochs"])

    clf = classifier.fit_classifier(train_features, train_arrays["labels"])
    train_pred, train_posterior = classifier.predict_intent(clf, train_features)
    test_pred, test_posterior = classifier.predict_intent(clf, test_features)

    train_accuracy = float(np.mean(train_pred == train_arrays["labels"]))
    test_accuracy = float(np.mean(test_pred == test_labels))

    return {
        "subject": subject,
        "verified_files": {k: {"sha256": v["sha256"], "key": v["key"]} for k, v in verified_files.items()},
        "label_names": train_arrays["label_names"],
        "classes_order": list(clf.classes_),
        "train": {
            "arrays": train_arrays,
            "artifact": train_af,
            "features": train_features,
            "predicted": train_pred,
            "posterior": train_posterior,
            "accuracy": train_accuracy,
            "n_trials": len(train_arrays["labels"]),
        },
        "test": {
            "arrays": test_arrays,
            "artifact": test_af,
            "features": test_features,
            "predicted": test_pred,
            "posterior": test_posterior,
            "accuracy": test_accuracy,
            "n_trials": len(test_labels),
            "labels": test_labels,
        },
        "fitted_features": fitted_features,
        "classifier": clf,
    }
