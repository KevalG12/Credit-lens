"""Dashboard summary: trend, goal plan, alerts, factor movers, offers preview. Pure functions over stored results."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.offers import match_cards, match_loans
from app.services.scoring import Model

NEXT_BANDS = [(500, "Fair"), (650, "Good"), (750, "Excellent")]
CHECK_EVERY_DAYS = 30


def _parse(ts: str) -> datetime:
    d = datetime.fromisoformat(ts)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def plan_to_reach(model: Model, features: dict, tips: list[dict], target: int) -> dict:
    """Apply the tips cumulatively (each to its target value) and re-score with the real model after each one."""
    cur, steps = dict(features), []
    score = model.score(cur)
    for t in tips:
        cur[t["feature"]] = t["target_value"]
        score = model.score(cur)
        steps.append({"feature": t["feature"], "label": t["label"], "advice": t["advice"],
                      "from": t["current_display"], "to": t["target_display"], "score_after": score})
        if score >= target:
            break
    return {"target": target, "steps": steps, "reachable": score >= target, "final_score": score}


def _movers(latest_factors: list[dict], prev_factors: list[dict] | None) -> list[dict]:
    if not prev_factors:
        return []
    prev = {f["feature"]: f for f in prev_factors}
    rows = []
    for f in latest_factors:
        p = prev.get(f["feature"])
        if p:
            rows.append({"feature": f["feature"], "label": f["label"], "delta": round(f["points"] - p["points"], 1)})
    rows.sort(key=lambda r: -abs(r["delta"]))
    return rows[:3]


def build_dashboard(model: Model, summaries: list[dict], latest: dict | None, previous: dict | None,
                    now: datetime | None = None) -> dict:
    """summaries: newest first ({id, score, band, created_at}); latest/previous: full stored rows or None."""
    now = now or datetime.now(timezone.utc)
    if not summaries or latest is None:
        return {"has_scores": False}
    res, feats = latest["result"], latest["features"]
    cur = summaries[0]
    prev_s = summaries[1] if len(summaries) > 1 else None
    delta = cur["score"] - prev_s["score"] if prev_s else None
    created = _parse(cur["created_at"])
    days_since = max(0, (now - created).days)
    due = created + timedelta(days=CHECK_EVERY_DAYS)
    scores = [s["score"] for s in summaries]

    nxt = next(((t, n) for t, n in NEXT_BANDS if cur["score"] < t), None)
    goal = {"kind": "reach", "next_band": nxt[1], "target": nxt[0], "points_to_go": nxt[0] - cur["score"],
            **plan_to_reach(model, feats, res.get("tips", []), nxt[0])} if nxt else \
        {"kind": "maintain", "next_band": None, "target": 750, "points_to_go": 0, "steps": [], "reachable": True,
         "points_above": cur["score"] - 750}

    factors = sorted(res.get("factors", []), key=lambda f: f["points"])
    movers = _movers(res.get("factors", []), previous["result"].get("factors") if previous else None)

    alerts = []
    if delta is not None and delta <= -20:
        why = f" Biggest change: {movers[0]['label']} ({movers[0]['delta']:+.0f} pts)." if movers else ""
        alerts.append({"level": "warn", "text": f"Your score fell {abs(delta)} points since your last check.{why}"})
    elif delta is not None and delta >= 20:
        why = f" Biggest gain: {movers[0]['label']} ({movers[0]['delta']:+.0f} pts)." if movers else ""
        alerts.append({"level": "good", "text": f"Your score rose {delta} points since your last check.{why}"})
    if prev_s and prev_s["band"] != cur["band"]:
        alerts.append({"level": "good" if delta and delta > 0 else "warn",
                       "text": f"Your band changed from {prev_s['band']} to {cur['band']}."})
    if days_since > CHECK_EVERY_DAYS:
        alerts.append({"level": "info", "text": f"It has been {days_since} days since your last check. "
                                                "Upload a fresh statement to see your progress."})
    if feats.get("bill_punctuality", 1) < 0.8:
        alerts.append({"level": "warn", "text": f"Only {feats['bill_punctuality'] * 100:.0f}% of your bills were paid on "
                                                "time. This is usually the fastest way to gain points."})
    if feats.get("emi_burden", 0) > 0.40:
        alerts.append({"level": "warn", "text": f"Loan EMIs take {feats['emi_burden'] * 100:.0f}% of your income, which "
                                                "limits new credit."})
    if feats.get("savings_ratio", 1) < 0.05:
        alerts.append({"level": "info", "text": "You are saving very little each month. Even 5% helps your score."})
    if feats.get("history_months", 12) < 6:
        alerts.append({"level": "info", "text": "Your history is short. Adding more months makes the score more reliable."})
    order = {"warn": 0, "good": 1, "info": 2}
    alerts.sort(key=lambda a: order[a["level"]])

    loans = match_loans(cur["score"], feats)
    cards = match_cards(cur["score"], feats, (res.get("profile") or {}).get("spend_share"))
    elig = [x for x in loans if x["status"] == "eligible"]
    personal = [x for x in elig if x["type"] == "personal"]
    rec = [c for c in cards["cards"] if c.get("recommended")]
    return {
        "has_scores": True,
        "latest": {"id": cur["id"], "score": cur["score"], "band": cur["band"], "created_at": cur["created_at"],
                   "score_min": res.get("score_min", 300), "score_max": res.get("score_max", 900),
                   "days_since": days_since, "next_check_due": due.isoformat(timespec="seconds"),
                   "check_overdue": now > due},
        "change": {"vs_previous": delta, "vs_first": cur["score"] - summaries[-1]["score"] if len(summaries) > 1 else None},
        "trend": [{"id": s["id"], "score": s["score"], "band": s["band"], "created_at": s["created_at"]}
                  for s in reversed(summaries[:24])],
        "stats": {"checks": len(summaries), "best": max(scores), "average": round(sum(scores) / len(scores))},
        "goal": goal,
        "helping": [f for f in reversed(factors) if f["points"] > 0.5][:3],
        "hurting": [f for f in factors if f["points"] < -0.5][:3],
        "movers": movers,
        "alerts": alerts[:5],
        "offers": {"eligible_loans": len(elig), "total_loans": len(loans),
                   "best_personal_rate": min((x["rate_apr"] for x in personal), default=None),
                   "cards_verdict": cards["advice"]["verdict"], "cards_verdict_title": cards["advice"]["title"],
                   "top_card": rec[0]["name"] if rec else None},
    }
