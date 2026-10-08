"""Explain a score in plain language.

The model is a logistic regression on standardised features, so exact additive
explanations (the linear-model case of SHAP) are available in closed form:

    points_i = -factor * coef_i * z_i       (z_i = standardised feature value)
    score    = baseline_score + sum(points_i)        (before 300-900 clipping)

so every factor's contribution is measured against the average applicant and the
contributions add up exactly to the score. No sampling, no approximation.
"""
from __future__ import annotations

import math

from app.config import DISCLAIMER
from app.services.features import BOUNDS, FEATURES
from app.services.scoring import SCORE_MAX, SCORE_MIN, Model, band_for


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _months(v: float) -> str:
    return f"{int(round(v))} months"


# display: how to print the value; positive / negative: reason templates ({d} = displayed value)
FEATURE_META = {
    "income_consistency": dict(
        label="Steady monthly income",
        display=_pct, kind="percent", step=0.05, target=0.85,
        positive="Your income arrives steadily month to month (consistency {d}).",
        negative="Your income swings a lot or skips months (consistency {d}).",
        advice="Aim for income that lands every month at a similar level, for example by keeping a regular client or a fixed retainer.",
    ),
    "savings_ratio": dict(
        label="Share of income saved",
        display=_pct, kind="percent", step=0.05, target=0.20,
        positive="You keep {d} of your income after spending.",
        negative="You keep only {d} of your income after spending.",
        advice="Move a fixed slice (even 5-10%) to savings as soon as income arrives, before spending.",
    ),
    "bill_punctuality": dict(
        label="On-time rent and bill payments",
        display=_pct, kind="percent", step=0.05, target=1.0,
        positive="{d} of your rent and bill payments were on time.",
        negative="Only {d} of your rent and bill payments were on time.",
        advice="Pay rent, utilities, mobile and EMIs on or before the due date. Autopay or reminders make this easy.",
    ),
    "rent_to_income": dict(
        label="Rent as a share of income",
        display=_pct, kind="percent", step=0.05, target=0.30,
        positive="Rent takes {d} of your income, a manageable share.",
        negative="Rent takes {d} of your income, which is a heavy share.",
        advice="A rent share near 30% of income helps. Sharing accommodation is the quickest lever.",
    ),
    "emi_burden": dict(
        label="Loan EMIs as a share of income",
        display=_pct, kind="percent", step=0.05, target=0.15,
        positive="Loan EMIs take only {d} of your income.",
        negative="Loan EMIs take {d} of your income.",
        advice="Keep EMIs under about 15% of income and hold off on new EMIs until existing ones shrink.",
    ),
    "spending_volatility": dict(
        label="Predictable spending",
        display=_pct, kind="percent", step=0.05, target=0.15,
        positive="Your month-to-month spending is predictable (variation {d}).",
        negative="Your month-to-month spending jumps around (variation {d}).",
        advice="Set a monthly budget and spread big purchases out so spending stays steady.",
    ),
    "history_months": dict(
        label="Length of history",
        display=_months, kind="months", step=1, target=12,
        positive="You have {d} of statement history, which makes the score more reliable.",
        negative="Only {d} of history, so the score is less certain.",
        advice="Confidence grows with history. Keep adding monthly statements until you reach about 12 months.",
    ),
}

assert set(FEATURE_META) == set(FEATURES), "FEATURE_META must cover every model feature"


def contributions_raw(model: Model, features: dict) -> dict:
    """Exact per-feature score contributions (unrounded), keyed by feature."""
    z = model.z(features)
    return {f: float(-model.factor * c * zi) for f, c, zi in zip(model.features, model.coef, z)}


def factors(model: Model, features: dict) -> list:
    raw = contributions_raw(model, features)
    out = []
    for f in model.features:
        meta, pts, val = FEATURE_META[f], raw[f], float(features[f])
        direction = "raises" if pts >= 1 else "lowers" if pts <= -1 else "neutral"
        template = meta["negative"] if pts < 0 else meta["positive"]
        if f == "savings_ratio" and val < 0:
            template = "You spent more than you earned over this period (net {d} of income)."
        out.append({
            "feature": f,
            "label": meta["label"],
            "value": round(val, 4),
            "display_value": meta["display"](val),
            "points": round(pts, 1),
            "direction": direction,
            "reason": template.format(d=meta["display"](val)),
        })
    return sorted(out, key=lambda x: abs(x["points"]), reverse=True)


def tips(model: Model, features: dict, max_tips: int = 3, min_gain: float = 3.0) -> list:
    """Suggest the changes that would add the most points (computed with the real model)."""
    base = model.score_unclipped(features)
    candidates = []
    for f in model.features:
        meta, val = FEATURE_META[f], float(features[f])
        target = meta["target"]
        better = (val < target) if model.higher_is_better(f) else (val > target)
        if not better:
            continue
        gain = model.score_unclipped({**features, f: target}) - base
        if gain >= min_gain:
            candidates.append({
                "feature": f,
                "label": meta["label"],
                "advice": meta["advice"],
                "current_display": meta["display"](val),
                "target_value": target,
                "target_display": meta["display"](target),
                "estimated_gain": int(round(gain)),
            })
    return sorted(candidates, key=lambda t: t["estimated_gain"], reverse=True)[:max_tips]


def build_result(model: Model, features: dict, warnings: list | None = None) -> dict:
    score = model.score(features)
    return {
        "score": score,
        "band": band_for(score),
        "score_min": SCORE_MIN,
        "score_max": SCORE_MAX,
        "probability_of_default": round(model.p_default(features), 4),
        "baseline_score": int(round(model.baseline_score())),
        "factors": factors(model, features),
        "tips": tips(model, features),
        "features": {f: round(float(features[f]), 4) for f in model.features},
        "warnings": list(warnings or []),
        "model_version": model.version,
        "disclaimer": DISCLAIMER,
    }


def feature_catalog(model: Model) -> list:
    """Metadata the frontend needs to draw one what-if slider per feature."""
    out = []
    for f in model.features:
        meta, (lo, hi) = FEATURE_META[f], BOUNDS[f]
        out.append({
            "name": f,
            "label": meta["label"],
            "kind": meta["kind"],
            "min": lo,
            "max": hi,
            "step": meta["step"],
            "target": meta["target"],
            "higher_is_better": model.higher_is_better(f),
        })
    return out
