from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app import db
from app.config import get_settings
from app.deps import get_current_user
from app.schemas import (DeleteResponse, ManualRequest, PreviewResponse, ScoreResponse, ScoreSummary,
                         SimulateRequest, SimulationResponse)
from app.services.explain import build_result
from app.services.features import StatementError, extract_features, extract_features_from_bytes
from app.services.ingest import load_statement, sample_rows
from app.services.manual import build_statement
from app.services.scoring import get_model
from app.services.simulate import SimulationError, simulate

router = APIRouter(tags=["scores"])


def _compute(data: bytes) -> tuple[dict, dict]:
    fr = extract_features_from_bytes(data)
    result = build_result(get_model(), fr.features, fr.warnings)
    rep = fr.report
    result["profile"] = fr.profile
    # keep only counts + the column mapping; never raw rows
    result["ingest"] = {k: rep[k] for k in ("mapping", "notes", "auto_categorised", "rows", "rows_ignored",
                                            "category_counts") if k in rep}
    return fr.features, result


def _preview(data: bytes) -> dict:
    df, rep = load_statement(data)
    out = {**rep, "warnings": [], "ready": True, "problem": None, "months": None,
           "date_from": None, "date_to": None, "sample": sample_rows(df)}
    if len(df):
        out["date_from"], out["date_to"] = df["date"].min().strftime("%Y-%m-%d"), df["date"].max().strftime("%Y-%m-%d")
    try:
        fr = extract_features(df)
        out["months"], out["warnings"] = fr.n_months, fr.warnings
    except StatementError as exc:
        out["ready"], out["problem"] = False, str(exc)
    return out


async def _read_upload(file: UploadFile) -> bytes:
    s = get_settings()
    data = await file.read(s.max_upload_bytes + 1)
    if len(data) > s.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"File too large (max {s.max_upload_bytes // 1000} KB).")
    return data


@router.post("/score/manual", response_model=ScoreResponse, status_code=201)
def score_manual(body: ManualRequest, user: dict = Depends(get_current_user)) -> ScoreResponse:
    """Score from typed-in figures instead of a CSV (same feature pipeline as a statement)."""
    if not body.consent:
        raise HTTPException(status_code=400, detail="Consent is required to calculate a score.")
    months = [m.model_dump() for m in body.months]
    if not any(m["income"] > 0 for m in months):
        raise HTTPException(status_code=422, detail="Enter your income for at least one month.")
    try:
        fr = extract_features(build_statement(months, body.bills_on_time_pct))
    except StatementError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    result = build_result(get_model(), fr.features, fr.warnings)
    result["profile"] = fr.profile
    result["ingest"] = {"source": "form", "rows": len(months), "rows_ignored": 0, "auto_categorised": 0,
                        "mapping": {}, "category_counts": {}, "notes": [f"Calculated from {len(months)} months of typed-in figures."]}
    s = get_settings()
    score_id, created_at = db.save_score(s.db_path, user["id"], result, True)
    return ScoreResponse(id=score_id, created_at=created_at, **result)


@router.post("/preview", response_model=PreviewResponse)
async def preview_statement(file: UploadFile = File(...), user: dict = Depends(get_current_user)) -> dict:
    """Show how a file would be interpreted (columns, auto-categories, issues). Stores nothing."""
    data = await _read_upload(file)
    try:
        return await run_in_threadpool(_preview, data)
    except StatementError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/score", response_model=ScoreResponse, status_code=201)
async def score_statement(
    file: UploadFile = File(..., description="CSV bank/UPI statement"),
    consent: bool = Form(..., description="User consents to processing this statement"),
    user: dict = Depends(get_current_user),
) -> ScoreResponse:
    s = get_settings()
    if not consent:
        raise HTTPException(status_code=400, detail="Consent is required to analyse a statement.")
    data = await _read_upload(file)
    try:
        _, result = await run_in_threadpool(_compute, data)
    except StatementError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    score_id, created_at = db.save_score(s.db_path, user["id"], result, consent)
    return ScoreResponse(id=score_id, created_at=created_at, **result)


@router.get("/scores", response_model=list[ScoreSummary])
def list_scores(user: dict = Depends(get_current_user)) -> list[dict]:
    return db.list_scores(get_settings().db_path, user["id"])


@router.get("/scores/{score_id}", response_model=ScoreResponse)
def get_score(score_id: int, user: dict = Depends(get_current_user)) -> ScoreResponse:
    row = db.get_score(get_settings().db_path, user["id"], score_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Score not found.")
    return ScoreResponse(id=row["id"], created_at=row["created_at"], **row["result"])


@router.post("/simulate", response_model=SimulationResponse)
def simulate_what_if(body: SimulateRequest, user: dict = Depends(get_current_user)) -> dict:
    row = db.get_score(get_settings().db_path, user["id"], body.score_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Score not found.")
    try:
        return simulate(get_model(), row["features"], body.overrides)
    except SimulationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.delete("/data", response_model=DeleteResponse)
def delete_my_data(delete_account: bool = False, user: dict = Depends(get_current_user)) -> DeleteResponse:
    n = db.delete_user_data(get_settings().db_path, user["id"], delete_account)
    return DeleteResponse(deleted_scores=n, account_deleted=delete_account)
