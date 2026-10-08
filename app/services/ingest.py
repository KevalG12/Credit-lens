"""Read real-world bank/UPI statement CSVs and normalise them to date, amount, category.

Real exports differ a lot: other column names (Narration, Withdrawal Amt.), separate
debit/credit columns, Dr/Cr markers, comma-formatted amounts, junk lines above the header,
no category column at all. This module hides that mess so features.py can stay strict.

Nothing here stores or logs row contents; the report returned holds only counts and the
column mapping (plus a few normalised sample rows for the preview screen).
"""
from __future__ import annotations

import csv
import io
import re

import numpy as np
import pandas as pd

from app.services.features import StatementError, _parse_dates

CATEGORIES = ["income", "rent", "utilities", "mobile", "emi", "food", "shopping",
              "transport", "subscription", "savings", "transfer", "other"]

# normalised header -> canonical name. Headers are lower-cased, punctuation stripped.
ALIASES = {
    "date": ["date", "txn date", "tran date", "transaction date", "value date", "posting date",
             "booking date", "trans date", "date of transaction"],
    "amount": ["amount", "transaction amount", "txn amount", "amt", "amount inr", "amount rs"],
    "debit": ["debit", "debit amount", "withdrawal", "withdrawals", "withdrawal amt", "withdrawal amount",
              "dr", "dr amount", "paid out", "money out", "debits"],
    "credit": ["credit", "credit amount", "deposit", "deposits", "deposit amt", "deposit amount",
               "cr", "cr amount", "paid in", "money in", "credits"],
    "description": ["description", "narration", "particulars", "remarks", "details", "transaction details",
                    "transaction remarks", "transaction description", "memo", "note", "notes", "merchant"],
    "category": ["category", "txn category", "transaction category"],
    "due_date": ["due date", "bill due date", "due"],
    "drcr": ["dr cr", "cr dr", "type", "transaction type", "txn type", "debit credit", "drcr"],
}
_ALIAS_LOOKUP = {a: canon for canon, names in ALIASES.items() for a in names}

CATEGORY_SYNONYMS = {
    "salary": "income", "stipend": "income", "earnings": "income", "payout": "income", "wages": "income",
    "bills": "utilities", "utility": "utilities", "electricity": "utilities", "internet": "utilities",
    "groceries": "food", "dining": "food", "restaurant": "food",
    "loan": "emi", "loans": "emi", "credit card": "emi",
    "investment": "savings", "investments": "savings", "sip": "savings",
    "fuel": "transport", "travel": "transport", "commute": "transport",
    "recharge": "mobile", "phone": "mobile", "subscriptions": "subscription", "entertainment": "subscription",
}

# Ordered rules: first match wins. Patterns use word boundaries to avoid false hits.
_RULES: list[tuple[str, str]] = [
    ("transfer", r"\b(self transfer|own account|to self|from self|wallet (load|top ?up)|neft to self)\b"),
    ("transfer", r"\b(refund|reversal|reversed|cashback|chargeback)\b"),
    ("savings", r"\b(sip|mutual fund|recurring deposit|rd installment|fixed deposit|ppf|nps|groww|zerodha|"
                r"investment|gold bees|smallcase|kuvera|coin by zerodha)\b"),
    ("emi", r"\b(emi|loan|instal?lment|repayment|bajaj fin\w*|home credit|kreditbee|moneyview|"
            r"credit card (bill|payment)|cred club|nach)\b"),
    ("rent", r"\b(rent|landlord|nobroker|nestaway|housing\.?com|pg (fee|rent)|hostel (fee|rent))\b"),
    ("mobile", r"\b(recharge|prepaid|postpaid|jio|airtel|vodafone|bsnl|mobile bill)\b"),
    ("utilities", r"\b(electricity|bescom|bses|tneb|mseb|tata power|adani electricity|water bill|gas bill|"
                  r"indane|hp gas|piped gas|broadband|fiber|fibre|wifi|act fibernet|utility)\b"),
    ("subscription", r"\b(netflix|spotify|prime video|amazon prime|hotstar|disney|youtube (premium|music)|"
                     r"apple\.com|google play|subscription|zee5|sonyliv|jiosaavn|audible)\b"),
    ("food", r"\b(swiggy|zomato|restaurant|cafe|dominos|domino s|mcdonald\w*|kfc|pizza|burger|starbucks|"
             r"bigbasket|blinkit|zepto|instamart|dmart|grocery|groceries|supermarket|bakery|food|eats|"
             r"chai|tea)\b"),
    ("transport", r"\b(uber|ola|rapido|irctc|metro|fuel|petrol|diesel|redbus|fastag|indigo|air india|"
                  r"cab|auto|bus|train|toll|parking|namma yatri)\b"),
    ("shopping", r"\b(amazon|flipkart|myntra|ajio|meesho|nykaa|shopping|mall|lifestyle|decathlon|"
                 r"ikea|reliance (digital|trends)|croma|snapdeal|store)\b"),
]
_COMPILED = [(cat, re.compile(pat, re.I)) for cat, pat in _RULES]

def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(h).lower())).strip()


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise StatementError("Could not read the file as text. Please export the statement as CSV.")


def _find_header(lines: list[str], delim: str) -> int:
    """Index of the first line that looks like a header (has a date column + an amount-ish column)."""
    for i, line in enumerate(lines[:60]):
        cells = {_ALIAS_LOOKUP.get(_norm_header(c)) for c in next(csv.reader([line], delimiter=delim), [])}
        if "date" in cells and cells & {"amount", "debit", "credit"}:
            return i
    return -1


def _sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:30])
    counts = {d: sample.count(d) for d in [",", ";", "\t", "|"]}
    return max(counts, key=counts.get) if max(counts.values()) else ","


def _to_number(series: pd.Series) -> pd.Series:
    """'1,23,456.50', 'Rs 500', '(250.00)', '500 Dr', '-40', '' -> floats.
    Parentheses, a minus sign or a 'Dr' marker make the value negative; unparseable -> NaN."""
    s = series.fillna("").astype(str).str.strip()
    neg = s.str.contains(r"^\(.*\)$|\bdr\b|-", case=False, regex=True)
    num = pd.to_numeric(s.str.replace(r"[^\d.]", "", regex=True), errors="coerce")
    return num.where(~neg, -num)


def classify(description: str, amount: float) -> str:
    """Guess a category from the free-text description (first matching rule wins)."""
    text = str(description or "")
    for cat, rx in _COMPILED:
        if rx.search(text):
            if amount < 0 or cat in ("transfer", "savings"):
                return cat
            break  # money IN that mentions a spending word (e.g. a customer paying 'food order'): treat as income
    return "income" if amount > 0 else "other"


def load_statement(data: bytes) -> tuple[pd.DataFrame, dict]:
    """Bytes -> (DataFrame[date, amount, category, (due_date), (description)], report)."""
    text = _decode(data)
    if not text.strip():
        raise StatementError("The file is empty.")
    delim = _sniff_delimiter(text)
    lines = text.splitlines()
    start = _find_header(lines, delim)
    notes: list[str] = []
    if start < 0:
        # fall back to row 0 and give a precise error about what we found
        first = next(csv.reader([lines[0]], delimiter=delim), [])
        raise StatementError(
            "Couldn't find the date and amount columns. Found columns: "
            f"{', '.join(c.strip() for c in first if c.strip()) or '(none)'}. "
            "A statement needs a date column and either an amount column or debit/credit columns."
        )
    if start > 0:
        notes.append(f"Skipped {start} line(s) above the table header.")
    try:
        raw = pd.read_csv(io.StringIO("\n".join(lines[start:])), sep=delim, dtype=str,
                          skipinitialspace=True, on_bad_lines="skip", engine="python")
    except Exception as exc:
        raise StatementError("Could not read the file as a CSV statement.") from exc

    mapping: dict[str, str] = {}
    for col in raw.columns:
        canon = _ALIAS_LOOKUP.get(_norm_header(col))
        if canon and canon not in mapping:
            mapping[canon] = col
    raw = raw.dropna(how="all")
    if len(raw) == 0:
        raise StatementError("The statement has no transactions.")

    out = pd.DataFrame(index=raw.index)
    out["date"] = raw[mapping["date"]]

    if "amount" in mapping:
        amt = _to_number(raw[mapping["amount"]])
        if "drcr" in mapping:                       # amounts are all positive, a Dr/Cr column gives the sign
            kind = raw[mapping["drcr"]].fillna("").astype(str).str.lower()
            is_debit = kind.str.contains(r"\bdr\b|debit|withdraw|paid out|\bd\b", regex=True)
            is_credit = kind.str.contains(r"\bcr\b|credit|deposit|paid in|\bc\b", regex=True)
            if (is_debit | is_credit).any() and (amt.dropna() >= 0).all():
                amt = amt.abs().where(~is_debit, -amt.abs())
                notes.append(f"Used the '{mapping['drcr']}' column to tell money in from money out.")
        out["amount"] = amt
    else:
        debit = _to_number(raw[mapping["debit"]]).abs() if "debit" in mapping else 0.0
        credit = _to_number(raw[mapping["credit"]]).abs() if "credit" in mapping else 0.0
        out["amount"] = pd.Series(credit, index=raw.index).fillna(0.0) - pd.Series(debit, index=raw.index).fillna(0.0)
        used = [mapping[k] for k in ("debit", "credit") if k in mapping]
        notes.append(f"Combined '{' + '.join(used)}' into one signed amount.")

    desc = raw[mapping["description"]].fillna("") if "description" in mapping else pd.Series("", index=raw.index)
    out["description"] = desc.astype(str)
    if "due_date" in mapping:
        out["due_date"] = raw[mapping["due_date"]]

    auto = 0
    if "category" in mapping:
        cat = raw[mapping["category"]].fillna("").astype(str).str.strip().str.lower()
        cat = cat.map(lambda c: CATEGORY_SYNONYMS.get(c, c))
        unknown = ~cat.isin(CATEGORIES)
        if unknown.any():
            fixed = [classify(d, a if pd.notna(a) else 0.0) for d, a in zip(out.loc[unknown, "description"], out.loc[unknown, "amount"])]
            cat = cat.copy()
            cat[unknown] = fixed
            auto = int(unknown.sum())
            notes.append(f"{auto} row(s) had a missing or unknown category and were categorised from their description.")
        out["category"] = cat
    else:
        out["category"] = [classify(d, a if pd.notna(a) else 0.0) for d, a in zip(out["description"], out["amount"])]
        auto = len(out)
        notes.append("No category column, so every row was categorised automatically from its description. "
                     "Check the breakdown below, and add a category column for full control.")
        if "description" not in mapping:
            notes.append("No description column was found either, so money in counts as income and money out as 'other'.")

    # statement summary / opening-balance lines have no valid date: drop them quietly but count them
    parsed = _parse_dates(out["date"])
    bad = parsed.isna() | out["amount"].isna()
    out = out.assign(date=parsed)
    dropped = int(bad.sum())
    if dropped and bad.mean() <= 0.2:
        notes.append(f"{dropped} row(s) without a valid date or amount were ignored.")
        out = out[~bad]
    elif dropped:
        raise StatementError("More than 20% of rows have an invalid date or amount. "
                             "Dates should look like 2026-01-31 or 31/01/2026.")

    report = {
        "mapping": {k: v for k, v in mapping.items()},
        "notes": notes,
        "auto_categorised": auto,
        "rows": int(len(out)),
        "rows_ignored": dropped,
        "category_counts": {k: int(v) for k, v in out["category"].value_counts().items()},
    }
    out = out.reset_index(drop=True)
    return out, report


def sample_rows(df: pd.DataFrame, n: int = 8) -> list[dict]:
    rows = []
    for _, r in df.head(n).iterrows():
        rows.append({
            "date": r["date"].strftime("%Y-%m-%d") if pd.notna(r["date"]) else "",
            "description": str(r.get("description", ""))[:60],
            "amount": float(r["amount"]),
            "category": r["category"],
        })
    return rows
