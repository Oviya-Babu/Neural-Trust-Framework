"""Classification -> predicted intent (CLAUDE.md §2, §17a, Phase 7).
Substrate only.

Logistic regression over the tangent-space features (bci_pipeline/
features.py) is the standard pairing for the Riemannian tangent-space
baseline throughout the BCI literature and in MOABB's own reference
pipelines (Barachant et al. 2013; Jayaram & Barachant 2018 -- see
features.py's docstring for full citations). Trained on session T (train),
evaluated on session E (test) -- the cross-session protocol §17a pins as
the reason this dataset was selected.

Emits the full posterior vector, not just the argmax -- Phase 8's Model OOD
and Calibration drift claims need the distribution (§17a), not a single
predicted label.
"""

from sklearn.linear_model import LogisticRegression

MAX_ITER = 1000


def fit_classifier(features_train, labels_train):
    clf = LogisticRegression(max_iter=MAX_ITER)
    clf.fit(features_train, labels_train)
    return clf


def predict_intent(clf, features):
    """Returns (predicted_labels, posterior) -- posterior is the full
    (n_trials, n_classes) probability vector in clf.classes_ order, not
    just argmax."""
    predicted = clf.predict(features)
    posterior = clf.predict_proba(features)
    return predicted, posterior
