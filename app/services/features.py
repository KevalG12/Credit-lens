"""Turn a bank/UPI statement CSV into the 7 model features.

The SAME function is used when generating training data and when serving,
so there is no train/serve mismatch.

Expected CSV columns (case-insensitive):
  date      YYYY-MM-DD (ISO), or day-first such as 05/01/2026 as most Indian banks export
  amount    positive = money in, negative = money out
  category  income, rent, utilities, mobile, emi, food, shopping, transport,
            subscription, savings, transfer, other
  due_date  optional, YYYY-MM-DD, for rent/utilities/mobile/emi payments
  description  optional
"""
from __future__ import annotations

import io
import warnings as _warnings
from dataclasses import dataclass, field

import pandas as pd

FEATURES = [
    "income_consistency",
    "savings_ratio",
    "bill_punctuality",
    "rent_to_income",
    "emi_burden",
    "spending_volatility",
    "history_months",
]

# Natural bounds for every feature (also used for slider ranges and clipping).
BOUNDS = {
    "income_consistency": (0.0, 1.0),
    "savings_ratio": (-1.0, 1.0),
    "bill_punctuality": (0.0, 1.0),
    "rent_to_income": (0.0, 1.5),
    "emi_burden": (0.0, 1.5),
    "spending_volatility": (0.0, 1.5),
    "history_months": (1.0, 12.0),
}

# Business-rule monotonicity: the sign each coefficient MUST have in the
# default-risk model (+ means "higher value -> higher risk of default").
EXPECTED_SIGN = {
    "income_consistency": -1,
    "savings_ratio": -1,
    "bill_punctuality": -1,
    "rent_to_income": +1,
    "emi_burden": +1,
    "spending_volatility": +1,
    "history_months": -1,
}

REQUIRED_COLUMNS = {"date", "amount", "category"}
BILL_CATEGORIES = {"rent", "utilities", "mobile", "emi"}
# Spending that a credit card could carry, grouped for reward matching (rent and EMIs are excluded).
CARD_GROUPS = {"food": "food", "shopping": "shopping", "transport": "transport", "utilities": "bills",
               "mobile": "bills", "subscription": "subscription", "other": "other"}
NON_SPEND_CATEGORIES = {"income", "savings", "transfer"}
GRACE_DAYS = 2
DEFAULT_PUNCTUALITY = 0.7
MIN_MONTHS = 3
MAX_ROWS = 20000


class StatementError(ValueError):
    """The uploaded statement is unusable; the message is safe to show the user."""


@dataclass
class FeatureResult:
    features: dict
    warnings: list = field(default_factory=list)
    n_transactions: int = 0
    n_months: int = 0
    report: dict = field(default_factory=dict)   # how the file was understood (see ingest.py)
    profile: dict = field(default_factory=dict)  # non-model facts for offers, e.g. spend_share (ratios only)


def clip_feature(name: str, value: float) -> float:
    lo, hi = BOUNDS[name]
    return float(min(max(value, lo), hi))


def _cv(series: pd.Series) -> float:
    mean = float(series.mean())
    if mean <= 0:
        return 0.0
    return float(series.std(ddof=0) / mean)


def _spend_share(df: pd.DataFrame, spend_mask: pd.Series) -> dict:
    """Share of card-eligible spending by group (ratios only, so no absolute amounts are kept)."""
    sp = df.loc[spend_mask & df["category"].isin(CARD_GROUPS)]
    if sp.empty:
        return {}
    by = (-sp["amount"]).groupby(sp["category"].map(CARD_GROUPS)).sum()
    tot = float(by.sum())
    return {k: round(float(v) / tot, 3) for k, v in by.items()} if tot > 0 else {}


def _parse_dates(series: pd.Series) -> pd.Series:
    """Parse each value as ISO (YYYY-MM-DD) first; values that are not ISO are parsed
    day-first (DD/MM/YYYY), the common Indian bank export format. Blanks stay NaT."""
    parsed = pd.to_datetime(series, format="ISO8601", errors="coerce")
    present = series.notna() & (series.astype(str).str.strip() != "")
    retry = parsed.isna() & present
    if retry.any():
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            parsed[retry] = pd.to_datetime(series[retry], dayfirst=True, errors="coerce")
    return parsed


def extract_features_from_bytes(data: bytes) -> FeatureResult:
    """Accepts our own format AND typical bank exports (see services/ingest.py)."""
    from app.services.ingest import load_statement   # local import: ingest imports this module
    df, report = load_statement(data)
    result = extract_features(df)
    result.report = report
    return result


def extract_features(df: pd.DataFrame) -> FeatureResult:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise StatementError(f"Missing required column(s): {', '.join(sorted(missing))}.")
    if len(df) == 0:
        raise StatementError("The statement has no transactions.")
    if len(df) > MAX_ROWS:
        raise StatementError(f"Statement too large (max {MAX_ROWS} rows).")

    warnings: list = []
    df["date"] = _parse_dates(df["date"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["category"] = df["category"].astype(str).str.strip().str.lower()

    bad = df["date"].isna() | df["amount"].isna()
    if bad.mean() > 0.2:
        raise StatementError("More than 20% of rows have an invalid date or amount.")
    if bad.any():
        warnings.append(f"{int(bad.sum())} row(s) with invalid date or amount were ignored.")
        df = df[~bad]

    df["m"] = df["date"].dt.year * 12 + df["date"].dt.month
    m0, m1 = int(df["m"].min()), int(df["m"].max())
    months = list(range(m0, m1 + 1))
    n_months = len(months)
    if n_months < MIN_MONTHS:
        raise StatementError(f"Need at least {MIN_MONTHS} months of transactions; found {n_months}.")

    def monthly(mask: pd.Series, sign: float = 1.0) -> pd.Series:
        return (sign * df.loc[mask, "amount"]).groupby(df.loc[mask, "m"]).sum().reindex(months, fill_value=0.0)

    income_mask = (df["category"] == "income") & (df["amount"] > 0)
    monthly_income = monthly(income_mask)
    total_income = float(monthly_income.sum())
    if total_income <= 0:
        raise StatementError("No income found. Rows with category 'income' and a positive amount are required.")

    spend_mask = (df["amount"] < 0) & (~df["category"].isin(NON_SPEND_CATEGORIES))
    monthly_spend = monthly(spend_mask, sign=-1.0)
    total_spend = float(monthly_spend.sum())

    rent_total = float((-df.loc[(df["category"] == "rent") & (df["amount"] < 0), "amount"]).sum())
    emi_total = float((-df.loc[(df["category"] == "emi") & (df["amount"] < 0), "amount"]).sum())

    # Bill punctuality: paid on or before due_date (+ grace days)
    punctuality = DEFAULT_PUNCTUALITY
    if "due_date" in df.columns:
        due = _parse_dates(df["due_date"])
        bill_mask = df["category"].isin(BILL_CATEGORIES) & (df["amount"] < 0) & due.notna()
        if int(bill_mask.sum()) >= 3:
            on_time = df.loc[bill_mask, "date"] <= due[bill_mask] + pd.Timedelta(days=GRACE_DAYS)
            punctuality = float(on_time.mean())
        else:
            warnings.append("Too few dated bill payments found; a neutral punctuality value was used.")
    else:
        warnings.append("No due_date column; a neutral punctuality value was used.")

    raw = {
        # 1 - coefficient of variation of monthly income; months with no income count as 0
        "income_consistency": 1.0 - _cv(monthly_income),
        "savings_ratio": (total_income - total_spend) / total_income,
        "bill_punctuality": punctuality,
        "rent_to_income": rent_total / total_income,
        "emi_burden": emi_total / total_income,
        "spending_volatility": _cv(monthly_spend),
        "history_months": float(n_months),
    }
    features = {k: round(clip_feature(k, v), 4) for k, v in raw.items()}
    return FeatureResult(features=features, warnings=warnings, n_transactions=int(len(df)), n_months=n_months,
                         profile={"spend_share": _spend_share(df, spend_mask)})
