"""Load the trained model and turn features into a 300-900 score.

Score scaling (standard "points to double the odds" method):
    odds_good = (1 - p_default) / p_default
    score = BASE_SCORE + PDO / ln(2) * ln(odds_good / BASE_ODDS)
clipped to 300-900. The values come from the trained model file; with the
current ones 600 points means 4:1 odds of repaying (the average applicant in
the synthetic population) and every +80 points doubles those odds.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.services.features import FEATURES, clip_feature

SCORE_MIN, SCORE_MAX = 300, 900

BANDS = [(750, "Excellent"), (650, "Good"), (500, "Fair"), (0, "Poor")]


def band_for(score: int) -> str:
    for threshold, name in BANDS:
        if score >= threshold:
            return name
    return "Poor"


class Model:
    def __init__(self, bundle: dict) -> None:
        if bundle["features"] != FEATURES:
            raise ValueError("Model features do not match the feature extractor; retrain the model.")
        self.bundle = bundle
        self.features = list(bundle["features"])
        self.mean = np.array(bundle["mean"], dtype=float)
        self.scale = np.array(bundle["scale"], dtype=float)
        self.coef = np.array(bundle["coef"], dtype=float)
        self.intercept = float(bundle["intercept"])
        self.factor = bundle["pdo"] / math.log(2)
        self.offset = bundle["base_score"] - self.factor * math.log(bundle["base_odds"])
        self.version = bundle["version"]
        self.metrics = bundle.get("metrics", {})

    @classmethod
    def load(cls, path: str | Path) -> "Model":
        return cls(json.loads(Path(path).read_text()))

    def vector(self, features: dict) -> np.ndarray:
        missing = [f for f in self.features if f not in features]
        if missing:
            raise ValueError(f"Missing feature(s): {', '.join(missing)}")
        return np.array([clip_feature(f, float(features[f])) for f in self.features])

    def z(self, features: dict) -> np.ndarray:
        return (self.vector(features) - self.mean) / self.scale

    def logit_default(self, features: dict) -> float:
        return float(self.intercept + self.coef @ self.z(features))

    def p_default(self, features: dict) -> float:
        return float(1 / (1 + math.exp(-self.logit_default(features))))

    def baseline_score(self) -> float:
        """Unclipped score of an 'average' applicant (all standardised features = 0)."""
        return self.offset + self.factor * (-self.intercept)

    def score_unclipped(self, features: dict) -> float:
        return self.offset + self.factor * (-self.logit_default(features))

    def score(self, features: dict) -> int:
        return int(round(min(max(self.score_unclipped(features), SCORE_MIN), SCORE_MAX)))

    def higher_is_better(self, feature: str) -> bool:
        """Higher feature value lowers default risk -> raises the score."""
        return bool(self.coef[self.features.index(feature)] < 0)


@lru_cache(maxsize=1)
def get_model() -> Model:
    return Model.load(get_settings().model_path)
