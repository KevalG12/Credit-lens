from fastapi import APIRouter

from app.config import DISCLAIMER
from app.schemas import FeatureInfo, ModelInfo
from app.services.explain import feature_catalog
from app.services.scoring import BANDS, SCORE_MAX, SCORE_MIN, get_model

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "model_version": get_model().version}


@router.get("/features", response_model=list[FeatureInfo])
def features() -> list[dict]:
    """Slider metadata for the what-if simulator."""
    return feature_catalog(get_model())


@router.get("/model-info", response_model=ModelInfo)
def model_info() -> dict:
    m = get_model()
    return {
        "version": m.version,
        "trained_on": m.bundle.get("trained_on", ""),
        "metrics": {k: float(v) for k, v in m.metrics.items()},
        "score_min": SCORE_MIN,
        "score_max": SCORE_MAX,
        "bands": [{"name": name, "from": threshold} for threshold, name in reversed(BANDS)],
        "disclaimer": DISCLAIMER,
    }
