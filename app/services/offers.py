"""Loan and credit-card matching.

The engine is a pure function of (score, features, optional user inputs) and a *catalogue* of
products. Where the catalogue comes from is a provider: the bundled provider reads
app/catalog/*.json (indicative sample terms). A real integration implements OfferProvider with live
lender/issuer data (see REAL_BANK_APIS.md); nothing else in the app changes.

Absolute income is never a model feature and is never stored. When a user optionally types their
monthly income on the offers screen it is used only for that request, to size an affordable loan.
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import BASE_DIR

CATALOG_DIR = BASE_DIR / "app" / "catalog"
CLOSE_GAP = 60          # within this many points of a minimum score counts as "close"
FOIR_CAP = 0.50         # lenders typically allow total EMIs up to ~50% of income


# ---------------------------------------------------------------- providers
class OfferProvider(Protocol):
    def loan_catalog(self) -> dict: ...
    def card_catalog(self) -> dict: ...


class StaticCatalogProvider:
    """Reads the bundled JSON catalogues (indicative sample terms)."""

    def __init__(self, directory: Path = CATALOG_DIR) -> None:
        self.dir = directory

    @lru_cache(maxsize=1)
    def loan_catalog(self) -> dict:
        return json.loads((self.dir / "loans.json").read_text())

    @lru_cache(maxsize=1)
    def card_catalog(self) -> dict:
        return json.loads((self.dir / "cards.json").read_text())


def get_provider() -> OfferProvider:
    """CREDITLENS_OFFER_PROVIDER=static (default). Add your own provider class here and select it by name."""
    name = os.getenv("CREDITLENS_OFFER_PROVIDER", "static").lower()
    if name == "static":
        return _STATIC
    raise RuntimeError(f"Unknown CREDITLENS_OFFER_PROVIDER '{name}'. See REAL_BANK_APIS.md.")


_STATIC = StaticCatalogProvider()


# ---------------------------------------------------------------- maths
def emi(principal: float, annual_rate_pct: float, months: int) -> float:
    """Equated monthly instalment. Zero-rate loans are principal / months."""
    if months <= 0:
        raise ValueError("months must be positive")
    r = annual_rate_pct / 1200.0
    if r == 0:
        return principal / months
    f = (1 + r) ** months
    return principal * r * f / (f - 1)


def affordable_principal(monthly_emi: float, annual_rate_pct: float, months: int) -> float:
    """Largest loan whose EMI is monthly_emi (inverse of emi())."""
    r = annual_rate_pct / 1200.0
    if r == 0:
        return monthly_emi * months
    return monthly_emi * (1 - (1 + r) ** -months) / r


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def indicative_rate(p: dict, score: int, top_score: float) -> float:
    """Better score -> rate moves from rate_worst (at min_score) to rate_best (at top_score)."""
    lo, hi = p["min_score"], max(top_score, p["min_score"] + 1)
    t = _clamp01((score - lo) / (hi - lo))
    return round(p["rate_worst"] - (p["rate_worst"] - p["rate_best"]) * t, 2)


def _roundto(x: float, step: int) -> int:
    return int(math.floor(x / step) * step)


# ---------------------------------------------------------------- loans
def match_loans(score: int, features: dict, monthly_income: float | None = None,
                provider: OfferProvider | None = None) -> list[dict]:
    cat = (provider or get_provider()).loan_catalog()
    top = cat.get("top_score", 800)
    months_hist = features.get("history_months", 0)
    emi_burden = features.get("emi_burden", 0.0)
    out = []
    for p in cat["products"]:
        gap = max(0, p["min_score"] - score)
        blockers = []
        if gap:
            blockers.append(f"Needs a score of {p['min_score']} (you are {gap} points short).")
        if months_hist < p["min_history_months"]:
            blockers.append(f"Needs about {p['min_history_months']} months of history (you have {int(months_hist)}).")
        if emi_burden > p["max_emi_burden"]:
            blockers.append(f"Your existing EMIs ({emi_burden * 100:.0f}% of income) are above this lender's "
                            f"{p['max_emi_burden'] * 100:.0f}% limit.")
        other = [b for b in blockers if not b.startswith("Needs a score")]
        if not blockers:
            status = "eligible"
        elif gap <= CLOSE_GAP and len(other) <= 1:
            status = "close"            # one realistic step away
        else:
            status = "not_yet"
        rate = indicative_rate(p, max(score, p["min_score"]), top)   # rate shown for the lowest qualifying score if not eligible
        lo_t, hi_t = p["tenure"]
        item = {
            "id": p["id"], "type": p["type"], "name": p["name"], "provider_type": p["provider_type"],
            "status": status, "rate_apr": rate, "rate_range": [p["rate_best"], p["rate_worst"]],
            "tenure_months": [lo_t, hi_t], "amount_range": p["amount"], "fee_pct": p["fee_pct"],
            "secured": p["secured"], "best_for": p["best_for"], "perks": p["perks"],
            "min_score": p["min_score"], "points_needed": gap, "blockers": blockers,
            "emi_per_lakh": round(emi(100000, rate, min(hi_t, max(lo_t, 36))), 0),
            "max_amount_for_you": None,
        }
        if monthly_income and monthly_income > 0:
            room = max(0.0, FOIR_CAP - emi_burden) * monthly_income          # EMI headroom per month
            cap = affordable_principal(room, rate, hi_t)
            item["max_amount_for_you"] = max(0, _roundto(min(cap, p["amount"][1]), 1000 if p["amount"][1] >= 100000 else 500))
            if item["max_amount_for_you"] < p["amount"][0]:
                item["blockers"] = blockers + ["Your income leaves too little room for this loan's minimum amount."]
                if item["status"] == "eligible":
                    item["status"] = "close"
        out.append(item)
    order = {"eligible": 0, "close": 1, "not_yet": 2}
    out.sort(key=lambda x: (order[x["status"]], x["rate_apr"], x["min_score"]))
    return out


# ---------------------------------------------------------------- cards
def card_advice(score: int, features: dict) -> dict:
    """Should this person get a credit card at all, and how should they use it?"""
    hist = features.get("history_months", 0)
    emi_b = features.get("emi_burden", 0.0)
    save = features.get("savings_ratio", 0.0)
    punct = features.get("bill_punctuality", 0.0)
    reasons: list[str] = []
    if score < 500:
        reasons.append(f"Your score ({score}) is in the Poor band, so most unsecured cards will decline you and a "
                       "rejection can pull the score down further.")
    if hist < 4:
        reasons.append(f"You have only {int(hist)} months of history. Issuers like to see 6+ months.")
    if emi_b > 0.35:
        reasons.append(f"Your loan EMIs already take {emi_b * 100:.0f}% of your income, so extra credit adds risk.")
    if save < 0.05:
        reasons.append("You save very little each month, which makes revolving card debt dangerous.")
    if punct < 0.8:
        reasons.append(f"Only {punct * 100:.0f}% of your bills are paid on time. A card's due date needs the same discipline.")

    if score < 500 or hist < 3 or emi_b > 0.50:
        verdict, title = "build_first", "Build first: a regular card is not your best next step"
        summary = ("A secured card (backed by a fixed deposit) or a credit-builder loan is the safest way to start a "
                   "record. Use it lightly, pay in full, and re-check your score in 3 months.")
    elif save < 0.05 and emi_b > 0.25:
        verdict, title = "caution", "Be careful: your budget has little room for credit"
        summary = "A card can help with rewards, but only if you pay the full bill every month. Start with a low limit."
    elif score >= 650 and punct >= 0.9 and emi_b <= 0.30:
        verdict, title = "good_fit", "A card makes sense for you"
        summary = "Your habits look reliable. Pick the card whose rewards match where you actually spend."
    else:
        verdict, title = "optional", "A card is optional right now"
        summary = ("A card can help build history and earn rewards, but you don't need one. If you take one, "
                   "choose a no-fee card and set autopay for the full amount.")
    if not reasons and verdict in ("good_fit", "optional"):
        reasons.append("No red flags in your statement: income, savings and repayments all look healthy.")
    rules = [
        "Keep usage under 30% of your limit.",
        "Pay the full statement amount by the due date; never just the minimum.",
        "Set autopay for the full amount so a due date is never missed.",
        "Apply for one card at a time: each rejected or new application can dent the score.",
    ]
    return {"verdict": verdict, "title": title, "summary": summary, "reasons": reasons, "rules": rules}


def _effective_reward(card: dict, share: dict, groups: list[str]) -> float:
    return sum(share.get(g, 0.0) * card["reward"].get(g, 0.0) for g in groups)


def match_cards(score: int, features: dict, spend_share: dict | None = None, monthly_spend: float | None = None,
                provider: OfferProvider | None = None) -> dict:
    cat = (provider or get_provider()).card_catalog()
    groups = cat["groups"]
    share = {g: float((spend_share or {}).get(g, 0.0)) for g in groups}
    tot = sum(share.values())
    used_default = tot <= 0
    share = dict(cat["default_share"]) if used_default else {g: v / tot for g, v in share.items()}

    advice = card_advice(score, features)
    hist = features.get("history_months", 0)
    cards = []
    for c in cat["cards"]:
        gap = max(0, c["min_score"] - score)
        blockers = []
        if gap:
            blockers.append(f"Needs a score of {c['min_score']} (you are {gap} points short).")
        if hist < c["min_history_months"]:
            blockers.append(f"Needs about {c['min_history_months']} months of history (you have {int(hist)}).")
        status = "eligible" if not blockers else ("close" if gap <= CLOSE_GAP and len(blockers) <= 2 else "not_yet")
        eff = _effective_reward(c, share, groups)
        best_group = max(groups, key=lambda g: share[g] * c["reward"].get(g, 0.0))
        item = {
            "id": c["id"], "name": c["name"], "issuer_type": c["issuer_type"], "tag": c["tag"], "status": status,
            "min_score": c["min_score"], "points_needed": gap, "blockers": blockers,
            "joining_fee": c["joining_fee"], "annual_fee": c["annual_fee"], "waiver_spend": c["waiver_spend"],
            "interest_apr": c["interest_apr"], "limit": c["limit"], "secured": c["secured"],
            "best_for": c["best_for"], "perks": c["perks"], "reward": c["reward"],
            "reward_rate_pct": round(eff, 2),
            "top_reward_group": best_group if share[best_group] * c["reward"].get(best_group, 0.0) > 0 else None,
            "net_annual_value": None, "fee_waived": None, "match_pct": 0,
        }
        if monthly_spend and monthly_spend > 0:
            yearly = monthly_spend * 12
            waived = c["waiver_spend"] > 0 and yearly >= c["waiver_spend"]
            fee = 0 if (c["annual_fee"] == 0 or waived) else c["annual_fee"]
            item["fee_waived"] = bool(waived)
            item["net_annual_value"] = round(yearly * eff / 100 - fee)
        cards.append(item)

    # rank: how well the rewards fit this person's spending (build cards ranked by simplicity instead)
    best_eff = max((c["reward_rate_pct"] for c in cards if c["status"] == "eligible" and c["tag"] != "build"), default=0.0)
    for c in cards:
        if c["tag"] == "build":
            c["match_pct"] = 100 if advice["verdict"] == "build_first" else 40
        else:
            fit = c["reward_rate_pct"] / best_eff if best_eff else 0
            fee_pen = 0.15 if c["annual_fee"] >= 2500 else 0.05 if c["annual_fee"] > 0 else 0
            c["match_pct"] = int(round(max(0.0, min(1.0, fit - fee_pen)) * 100))
        if advice["verdict"] == "build_first" and c["tag"] != "build":
            c["match_pct"] = min(c["match_pct"], 30)
    order = {"eligible": 0, "close": 1, "not_yet": 2}
    value = (lambda c: -(c["net_annual_value"] if c["net_annual_value"] is not None else 0))
    cards.sort(key=lambda c: (order[c["status"]], -c["match_pct"], value(c), c["annual_fee"]))
    eligible = [c for c in cards if c["status"] == "eligible"]
    for i, c in enumerate(eligible[:3]):
        c["recommended"] = True
    return {"advice": advice, "cards": cards, "spend_share": {g: round(v, 3) for g, v in share.items()},
            "spend_share_is_default": used_default}
