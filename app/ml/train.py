"""Train the scoring model on synthetic data and save it as plain JSON.

Run:  python -m app.ml.train

Model: standardised logistic regression predicting probability of default.
It is saved as plain numbers (mean, scale, coef, intercept) so the API needs
only numpy to serve it, and so explanations can be computed exactly.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from app.ml.synthetic import generate_dataset
from app.services.features import EXPECTED_SIGN, FEATURES

MODEL_PATH = Path(__file__).resolve().parent / "model.json"

def fit_sign_constrained(Z: np.ndarray, y: np.ndarray):
    """Logistic regression where any feature with a wrong-signed coefficient is
    dropped (coefficient forced to 0) and the model is refit. This keeps
    explanations sensible: a feature can never be shown helping when it should hurt."""
    active = list(range(len(FEATURES)))
    dropped: list[str] = []
    while True:
        clf = LogisticRegression(C=1.0, max_iter=1000).fit(Z[:, active], y)
        bad = [i for i, c in zip(active, clf.coef_[0]) if np.sign(c) != EXPECTED_SIGN[FEATURES[i]]]
        if not bad:
            break
        # drop the worst offender first, then refit
        worst = max(bad, key=lambda i: abs(clf.coef_[0][active.index(i)]))
        dropped.append(FEATURES[worst])
        active.remove(worst)
    coef = np.zeros(len(FEATURES))
    coef[active] = clf.coef_[0]
    return coef, float(clf.intercept_[0]), dropped

# Score scaling (see scoring.py): 600 points at 4:1 good:bad odds; every +80 points doubles the odds.
BASE_SCORE = 600  # score of an applicant with 4:1 odds of repaying (~20% default risk = the average here)
BASE_ODDS = 4
PDO = 80  # points to double the odds


def train(n: int = 4000, seed: int = 7, out: Path = MODEL_PATH) -> dict:
    X, y = generate_dataset(n, seed)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, random_state=seed, stratify=y)

    scaler = StandardScaler().fit(X_tr)
    coef, intercept, dropped = fit_sign_constrained(scaler.transform(X_tr), y_tr)

    z_te = scaler.transform(X_te)
    p_te = 1 / (1 + np.exp(-(intercept + z_te @ coef)))
    fpr, tpr, _ = roc_curve(y_te, p_te)
    metrics = {
        "auc": round(float(roc_auc_score(y_te, p_te)), 4),
        "ks": round(float(np.max(tpr - fpr)), 4),
        "brier": round(float(brier_score_loss(y_te, p_te)), 4),
        "default_rate": round(float(y.mean()), 4),
        "n_train": int(len(X_tr)),
        "n_test": int(len(X_te)),
    }
    bundle = {
        "version": "synthetic-logreg-v1",
        "trained_on": f"synthetic statements (n={n}, seed={seed})",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "features": FEATURES,
        "mean": [float(v) for v in scaler.mean_],
        "scale": [float(v) for v in scaler.scale_],
        "coef": [float(v) for v in coef],
        "intercept": intercept,
        "dropped_for_wrong_sign": dropped,
        "base_score": BASE_SCORE,
        "base_odds": BASE_ODDS,
        "pdo": PDO,
        "metrics": metrics,
    }
    Path(out).write_text(json.dumps(bundle, indent=2))
    return bundle


if __name__ == "__main__":
    b = train()
    print("saved", MODEL_PATH)
    print("metrics:", b["metrics"])
    print("dropped for wrong sign:", b["dropped_for_wrong_sign"])
    for name, c in zip(b["features"], b["coef"]):
        print(f"  {name:22s} coef={c:+.3f}")
    sys.exit(0)
