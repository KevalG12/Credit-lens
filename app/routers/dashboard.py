from fastapi import APIRouter, Depends

from app import db
from app.config import get_settings
from app.deps import get_current_user
from app.services.dashboard import build_dashboard
from app.services.scoring import get_model

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(user: dict = Depends(get_current_user)) -> dict:
    """Everything the home dashboard needs in one call: trend, goal plan, alerts, movers, offers preview."""
    path = get_settings().db_path
    summaries = db.list_scores(path, user["id"], limit=50)
    latest = db.get_score(path, user["id"], summaries[0]["id"]) if summaries else None
    previous = db.get_score(path, user["id"], summaries[1]["id"]) if len(summaries) > 1 else None
    return build_dashboard(get_model(), summaries, latest, previous)
