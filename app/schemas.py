"""Pydantic request/response contracts (the API contract the frontend builds against)."""
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Credentials(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    password: str = Field(min_length=8, max_length=128)


def password_problems(pw: str) -> list[str]:
    """Rules for NEW passwords (login accepts any existing one so old accounts still work)."""
    out = []
    if len(pw) < 8:
        out.append("at least 8 characters")
    if not re.search(r"[A-Z]", pw):
        out.append("one uppercase letter")
    if not re.search(r"[a-z]", pw):
        out.append("one lowercase letter")
    if not re.search(r"\d", pw):
        out.append("one number")
    if not re.search(r"[^A-Za-z0-9]", pw):
        out.append("one special character")
    return out


class RegisterCredentials(Credentials):
    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        problems = password_problems(v)
        if problems:
            raise ValueError("Password needs " + ", ".join(problems) + ".")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    email: str
    created_at: str
    is_guest: bool = False


class Factor(BaseModel):
    feature: str
    label: str
    value: float
    display_value: str
    points: float          # contribution to the score vs the average applicant
    direction: str         # "raises" | "lowers" | "neutral"
    reason: str            # plain-language sentence


class Tip(BaseModel):
    feature: str
    label: str
    advice: str
    current_display: str
    target_value: float
    target_display: str
    estimated_gain: int    # points, computed by re-scoring with the real model


class ScoreResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())  # allow the field name `model_version`

    id: int
    created_at: str
    score: int
    band: str
    score_min: int
    score_max: int
    probability_of_default: float
    baseline_score: int
    factors: list[Factor]
    tips: list[Tip]
    features: dict[str, float]
    warnings: list[str]
    model_version: str
    disclaimer: str
    ingest: dict | None = None            # how the statement was read (counts only, no raw rows)
    profile: dict | None = None           # non-model facts used by offers (spend shares, ratios only)


class PreviewResponse(BaseModel):
    """What the app understood from an uploaded file, shown BEFORE scoring (nothing is stored)."""
    ready: bool
    problem: str | None = None            # why scoring would fail, in plain language
    mapping: dict[str, str]               # detected columns, e.g. {"date": "Txn Date", ...}
    notes: list[str]
    warnings: list[str]
    rows: int
    rows_ignored: int
    auto_categorised: int
    category_counts: dict[str, int]
    months: int | None = None
    date_from: str | None = None
    date_to: str | None = None
    sample: list[dict]


class ScoreSummary(BaseModel):
    id: int
    score: int
    band: str
    created_at: str


class SimulateRequest(BaseModel):
    score_id: int
    overrides: dict[str, float] = Field(min_length=1)


class ChangedFeature(BaseModel):
    feature: str
    label: str
    from_value: float
    to_value: float


class SimulationResponse(BaseModel):
    original_score: int
    new_score: int
    delta: int
    original_band: str
    new_band: str
    changed: list[ChangedFeature]
    factors: list[Factor]
    tips: list[Tip]
    features: dict[str, float]
    disclaimer: str


class FeatureInfo(BaseModel):
    name: str
    label: str
    kind: str              # "percent" | "months" (how the frontend should format it)
    min: float
    max: float
    step: float
    target: float
    higher_is_better: bool


class ModelInfo(BaseModel):
    version: str
    trained_on: str
    metrics: dict[str, float]
    score_min: int
    score_max: int
    bands: list[dict]
    disclaimer: str


class DeleteResponse(BaseModel):
    deleted_scores: int
    account_deleted: bool


class ManualMonth(BaseModel):
    """One month of figures typed into the form (all amounts in rupees, never stored)."""
    income: float = Field(0, ge=0, le=1e8)
    rent: float = Field(0, ge=0, le=1e8)
    emi: float = Field(0, ge=0, le=1e8)
    bills: float = Field(0, ge=0, le=1e8)          # utilities, mobile, internet
    food: float = Field(0, ge=0, le=1e8)
    shopping: float = Field(0, ge=0, le=1e8)
    transport: float = Field(0, ge=0, le=1e8)
    subscription: float = Field(0, ge=0, le=1e8)
    other: float = Field(0, ge=0, le=1e8)
    savings: float = Field(0, ge=0, le=1e8)        # money moved to savings/investments


class ManualRequest(BaseModel):
    months: list[ManualMonth] = Field(min_length=3, max_length=12)
    bills_on_time_pct: float = Field(ge=0, le=100)
    consent: bool


class LoansResponse(BaseModel):
    score: int
    band: str
    summary: dict
    loans: list[dict]
    note: str


class CardsResponse(BaseModel):
    score: int
    band: str
    advice: dict
    cards: list[dict]
    spend_share: dict[str, float]
    spend_share_is_default: bool
    note: str
