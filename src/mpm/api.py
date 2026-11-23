"""Phase 10: FastAPI service.  Run:  uvicorn mpm.api:app --app-dir src   (MPM_MODEL_DIR overrides models/final)."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .serve import DISCLAIMER, Store

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "models" / "final"
DEFAULT_WEB = Path(__file__).resolve().parents[2] / "web"


class PointRequest(BaseModel):
    lon: float = Field(ge=-180, le=180, description="longitude, WGS84")
    lat: float = Field(ge=-90, le=90, description="latitude, WGS84")


class BBoxRequest(BaseModel):
    min_lon: float = Field(ge=-180, le=180)
    min_lat: float = Field(ge=-90, le=90)
    max_lon: float = Field(ge=-180, le=180)
    max_lat: float = Field(ge=-90, le=90)
    top_n: int = Field(10, ge=1, le=100, description="number of highest-ranked cells to list")

    @model_validator(mode="after")
    def _ordered(self):
        if self.min_lon >= self.max_lon or self.min_lat >= self.max_lat:
            raise ValueError("min_lon/min_lat must be smaller than max_lon/max_lat")
        return self


def create_app(model_dir: Path | None = None) -> FastAPI:
    mdir = Path(model_dir or os.environ.get("MPM_MODEL_DIR", DEFAULT_DIR))
    app = FastAPI(title="Uranium prospectivity (South Pass-Granite Mountains pilot)",
                  description=DISCLAIMER, version="0.1.0")
    state: dict = {}

    def store() -> Store:
        if "s" not in state:
            try:
                state["s"] = Store(mdir)
            except FileNotFoundError as e:
                raise HTTPException(503, f"model artefacts not found in {mdir}: {e.filename}")
        return state["s"]

    @app.get("/health")
    def health():
        ok = (mdir / "serving.npz").exists() and (mdir / "metadata.json").exists()
        return {"status": "ok" if ok else "model_missing"}

    @app.get("/model-info")
    def model_info():
        m = store().meta
        keep = ("created_utc", "model", "n_train_positives", "n_train_background", "features_used", "versions",
                "out_of_fold_performance_inclusive_phase8", "calibration_bins_out_of_fold_phase9", "gate_G4_met",
                "limitations", "wording_rule")
        return {k: m[k] for k in keep}

    @app.post("/predict/point")
    def predict_point(req: PointRequest):
        out = store().point(req.lon, req.lat)
        if out is None:
            raise HTTPException(404, "point is outside the surveyed footprint (or on a no-data cell)")
        return out

    @app.post("/predict/bbox")
    def predict_bbox(req: BBoxRequest):
        out = store().bbox(req.min_lon, req.min_lat, req.max_lon, req.max_lat, req.top_n)
        if out is None:
            raise HTTPException(404, "box does not overlap the surveyed footprint")
        return out

    def hot() -> dict:
        h = store().hot
        if h is None:
            raise HTTPException(503, f"hotspots.json not found in {mdir}; run scripts/run_pipeline.py (stage 10c_frontend_data)")
        return h

    @app.get("/hotspots")
    def hotspots(response: Response):
        """Hot-spot polygons in three tiers (GeoJSON, lon/lat) from the final map."""
        response.headers["Cache-Control"] = "public, max-age=3600"
        h = hot()
        return {"tier_defs": h["tier_defs"], "tiers": h["tiers"], "disclaimer": DISCLAIMER}

    @app.get("/areas")
    def areas(response: Response):
        """Ranked areas of interest (clusters of the top 5 % of the study area)."""
        response.headers["Cache-Control"] = "public, max-age=3600"
        return {"areas": hot()["areas"], "disclaimer": DISCLAIMER}

    @app.get("/known")
    def known(response: Response):
        """Known occurrence points (public USGS MRDS records) used as training labels."""
        response.headers["Cache-Control"] = "public, max-age=3600"
        return {"known": hot()["known"]}

    web = Path(os.environ.get("MPM_WEB_DIR", DEFAULT_WEB))
    if web.is_dir():                         # mounted last so the API routes above win
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app


app = create_app()
