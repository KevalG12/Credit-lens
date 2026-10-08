"""Synthetic statement generator (no real financial data is used anywhere).

Each applicant has hidden traits:
  discipline (0-1)  - how reliably they pay bills / how restrained their spending is
  stability  (0-1)  - how steady their income is
We generate a full bank statement from those traits, run it through the REAL
feature extractor, and draw a repayment outcome (default / no default) from the
hidden traits plus noise. The model only ever sees the extracted features.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.services.features import FEATURES, extract_features


@dataclass
class Profile:
    discipline: float
    stability: float
    base_income: float
    n_months: int
    rent_frac: float
    emi_frac: float  # 0 means no loan
    discretionary: float  # share of base income spent on food/shopping/etc.
    saves: bool
    volatility: float  # hidden trait: how erratic month-to-month spending is
    realized_regularity: float = 1.0  # share of months with income, set while generating the statement


def sample_profile(rng: np.random.Generator) -> Profile:
    discipline = float(rng.beta(4, 3))
    stability = float(rng.beta(3, 2.5))
    months = np.arange(3, 13)
    weights = np.linspace(1, 3, len(months))
    n_months = int(rng.choice(months, p=weights / weights.sum()))
    has_emi = rng.random() < 0.35
    return Profile(
        discipline=discipline,
        stability=stability,
        base_income=float(np.exp(rng.normal(np.log(28000), 0.45))),
        n_months=n_months,
        rent_frac=float(rng.uniform(0.12, 0.45)),
        emi_frac=float(rng.uniform(0.04, 0.22)) if has_emi else 0.0,
        discretionary=float(np.clip(rng.normal(0.30 + 0.25 * (1 - discipline), 0.06), 0.10, 0.70)),
        saves=bool(rng.random() < 0.15 + 0.7 * discipline),
        volatility=float(rng.beta(2, 6)),
    )


def default_probability(rng: np.random.Generator, p: Profile) -> float:
    logit = (
        -2.2
        + 4.0 * (0.5 - p.discipline)
        + 3.0 * (0.5 - p.stability)
        + 2.5 * (p.volatility - 0.25)
        + 5.0 * (p.discretionary - 0.4)
        + 3.0 * (1 - p.realized_regularity)  # missed income months hurt repayment
        + 4.0 * p.emi_frac
        + 5.0 * (p.rent_frac - 0.28)
        + 0.9 * (1 - p.n_months / 12)  # thin files are riskier
        + rng.normal(0, 0.35)
    )
    return float(1 / (1 + np.exp(-logit)))


def _month_start(start: date, offset: int) -> date:
    y = start.year + (start.month - 1 + offset) // 12
    m = (start.month - 1 + offset) % 12 + 1
    return date(y, m, 1)


def generate_statement(rng: np.random.Generator, p: Profile, start: date = date(2025, 10, 1)) -> pd.DataFrame:
    rows = []  # (date, description, amount, category, due_date)
    late_prob = float(np.clip((1 - p.discipline) * 0.9, 0.02, 0.9))
    cats = ["food", "shopping", "transport", "subscription"]
    cat_p = [0.5, 0.25, 0.2, 0.05]
    income_months = 0

    for i in range(p.n_months):
        ms = _month_start(start, i)

        def d(day: int) -> date:
            return ms + timedelta(days=int(day) - 1)

        # Income: salaried people get one credit, gig workers several smaller ones.
        has_income = rng.random() < min(1.0, 0.7 + 0.3 * p.stability) or (i == p.n_months - 1 and income_months == 0)
        if has_income:
            income_months += 1
            total = p.base_income * float(np.exp(rng.normal(0, 0.05 + 0.5 * (1 - p.stability))))
            n_credits = 1 + (int(rng.integers(1, 4)) if rng.random() > p.stability else 0)
            parts = rng.dirichlet(np.ones(n_credits)) * total
            for amt in parts:
                rows.append((d(int(rng.integers(1, 29))), "INCOME CREDIT", round(float(amt), 2), "income", ""))

        # Bills: (category, amount, due day)
        bills = [
            ("rent", p.rent_frac * p.base_income, 5),
            ("utilities", 0.035 * p.base_income * float(rng.uniform(0.8, 1.2)), 15),
            ("mobile", 0.02 * p.base_income, 20),
        ]
        if p.emi_frac > 0:
            bills.append(("emi", p.emi_frac * p.base_income, 10))
        for cat, amt, due_day in bills:
            due = d(due_day)
            if rng.random() < late_prob:
                paid = due + timedelta(days=int(rng.integers(3, 13)))
            else:
                paid = due - timedelta(days=int(rng.integers(0, 5)))
            rows.append((paid, f"{cat.upper()} PAYMENT", -round(float(amt), 2), cat, due.isoformat()))

        # Everyday spending
        total_disc = p.base_income * p.discretionary * float(np.exp(rng.normal(0, 0.05 + 0.6 * p.volatility)))
        k = int(rng.integers(8, 16))
        for w in rng.dirichlet(np.ones(k)):
            cat = str(rng.choice(cats, p=cat_p))
            rows.append((d(int(rng.integers(1, 29))), f"{cat.upper()} SPEND", -round(float(total_disc * w), 2), cat, ""))

        # Savings transfer
        if p.saves and rng.random() < 0.85:
            rows.append((d(25), "TRANSFER TO SAVINGS", -round(p.base_income * float(rng.uniform(0.03, 0.15)), 2), "savings", ""))

    p.realized_regularity = income_months / p.n_months
    df = pd.DataFrame(rows, columns=["date", "description", "amount", "category", "due_date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["date"] = df["date"].map(lambda x: x.isoformat())
    return df


def generate_dataset(n: int, seed: int = 7) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    feats, labels = [], []
    for _ in range(n):
        p = sample_profile(rng)
        stmt = generate_statement(rng, p)
        feats.append(extract_features(stmt).features)
        labels.append(int(rng.random() < default_probability(rng, p)))
    return pd.DataFrame(feats, columns=FEATURES), np.array(labels)
