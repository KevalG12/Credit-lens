from fastapi import APIRouter, Depends, HTTPException, Query

from app import db
from app.config import get_settings
from app.deps import get_current_user
from app.schemas import CardsResponse, LoansResponse
from app.services.offers import match_cards, match_loans
from app.services.scoring import band_for

router = APIRouter(tags=["offers"])

NOTE = "Indicative terms for comparison. The final rate, limit and approval are decided by the lender."


def _row(user: dict, score_id: int) -> dict:
    row = db.get_score(get_settings().db_path, user["id"], score_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Score not found.")
    return row


@router.get("/scores/{score_id}/loans", response_model=LoansResponse)
def loans_for_score(score_id: int, monthly_income: float | None = Query(None, ge=0, le=1e8),
                    user: dict = Depends(get_current_user)) -> dict:
    """Loan products matched to this score. `monthly_income` is optional, used only for this request."""
    row = _row(user, score_id)
    score = row["result"]["score"]
    loans = match_loans(score, row["features"], monthly_income)
    counts = {s: sum(1 for x in loans if x["status"] == s) for s in ("eligible", "close", "not_yet")}
    return {"score": score, "band": band_for(score), "summary": counts, "loans": loans, "note": NOTE}


@router.get("/scores/{score_id}/cards", response_model=CardsResponse)
def cards_for_score(score_id: int, monthly_spend: float | None = Query(None, ge=0, le=1e8),
                    user: dict = Depends(get_current_user)) -> dict:
    """Credit-card advice (do you need one?) and ranked cards for this score and spending mix."""
    row = _row(user, score_id)
    score = row["result"]["score"]
    share = (row["result"].get("profile") or {}).get("spend_share")
    out = match_cards(score, row["features"], share, monthly_spend)
    return {"score": score, "band": band_for(score), "note": NOTE, **out}
