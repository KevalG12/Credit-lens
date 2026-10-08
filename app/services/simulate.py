"""What-if simulation: re-score a stored result with some features changed."""
from __future__ import annotations

import math

from app.config import DISCLAIMER
from app.services.explain import FEATURE_META, build_result
from app.services.features import FEATURES, clip_feature
from app.services.scoring import Model


class SimulationError(ValueError):
    """Bad what-if input; message is safe to show the user."""


def simulate(model: Model, base_features: dict, overrides: dict) -> dict:
    if not overrides:
        raise SimulationError("Provide at least one feature to change.")
    new_features = dict(base_features)
    changed = []
    for name, raw in overrides.items():
        if name not in FEATURES:
            raise SimulationError(f"Unknown feature: {name}")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise SimulationError(f"Value for {name} must be a number.") from None
        if not math.isfinite(value):
            raise SimulationError(f"Value for {name} must be a finite number.")
        value = clip_feature(name, value)
        changed.append({
            "feature": name,
            "label": FEATURE_META[name]["label"],
            "from_value": round(float(base_features[name]), 4),
            "to_value": round(value, 4),
        })
        new_features[name] = value

    before, after = build_result(model, base_features), build_result(model, new_features)
    return {
        "original_score": before["score"],
        "new_score": after["score"],
        "delta": after["score"] - before["score"],
        "original_band": before["band"],
        "new_band": after["band"],
        "changed": changed,
        "factors": after["factors"],
        "tips": after["tips"],
        "features": after["features"],
        "disclaimer": DISCLAIMER,
    }
