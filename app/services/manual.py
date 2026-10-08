"""Score from a form instead of a CSV.

The form collects, per month: income, rent, EMIs, bills, food, shopping, transport, subscriptions, other
spending and savings, plus how often bills are paid on time. We turn that into the same transaction table a
CSV would give and run the SAME feature extraction, so a form score and a CSV score are directly comparable.
Nothing entered is stored; only the 7 ratios, the result and spend shares are.
"""
from __future__ import annotations

import math

import pandas as pd

MONTH_FIELDS = ["income", "rent", "emi", "bills", "food", "shopping", "transport", "subscription", "other", "savings"]
# form field -> statement category
CATEGORY = {"income": "income", "rent": "rent", "emi": "emi", "bills": "utilities", "food": "food",
            "shopping": "shopping", "transport": "transport", "subscription": "subscription",
            "other": "other", "savings": "savings"}
DAY = {"income": 1, "rent": 3, "emi": 6, "bills": 9, "food": 12, "shopping": 15, "transport": 18,
       "subscription": 21, "other": 24, "savings": 27}
DUE_OFFSET = {"rent": 2, "emi": 2, "bills": 2}      # bills fall due 2 days after our nominal payment day
LATE_DAYS = 6                                       # a "late" payment lands 6 days after its due date


def build_statement(months: list[dict], bills_on_time_pct: float, start_year: int = 2026) -> pd.DataFrame:
    rows = []
    bill_idx = []   # row indexes of dated bill payments, in time order
    for i, m in enumerate(months):
        year, mon = start_year + i // 12, i % 12 + 1
        for f in MONTH_FIELDS:
            amt = float(m.get(f, 0) or 0)
            if amt <= 0:
                continue
            day = DAY[f]
            date = pd.Timestamp(year, mon, day)
            due = date + pd.Timedelta(days=DUE_OFFSET[f]) if f in DUE_OFFSET else pd.NaT
            rows.append({"date": date, "description": f, "amount": amt if f == "income" else -amt,
                         "category": CATEGORY[f], "due_date": due})
            if f in DUE_OFFSET:
                bill_idx.append(len(rows) - 1)
    df = pd.DataFrame(rows, columns=["date", "description", "amount", "category", "due_date"])
    n = len(bill_idx)
    late = int(round((1 - max(0.0, min(100.0, bills_on_time_pct)) / 100.0) * n))
    # spread the late payments evenly across the period instead of bunching them at the end
    if late and n:
        step = n / late
        for k in range(late):
            j = bill_idx[min(n - 1, int(math.floor(k * step + step / 2)))]
            df.loc[j, "date"] = df.loc[j, "due_date"] + pd.Timedelta(days=LATE_DAYS)
    return df
