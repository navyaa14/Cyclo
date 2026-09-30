"""CYCLOPS API. Run: uvicorn app.main:app --reload (from backend/)."""
from __future__ import annotations

from .env_loader import load_env

load_env()  # reads cyclops/.env or backend/.env before any service reads the environment

import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .data import demo_scenario as D
from .engines import assets as A
from .engines import cascade as C
from .engines import hazard as H
from .engines import optimizer as O
from .engines import reach as RG
from .engines import verify as V
from .schemas import AlertRequest, BriefRequest, OptimizeRequest, ReviewRequest, SimRequest
from .services import comms, evaluation, gemini, reports

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="CYCLOPS", version="0.3.0",
              description="Cyclone Impact & Infrastructure Resilience Twin (hackathon prototype)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
MAX_UPLOAD = 6 * 1024 * 1024

# --- simple per-IP rate limit for report ingestion -------------------------------------------------
_RATE: dict[str, deque] = defaultdict(deque)
RATE_LIMIT = int(os.getenv("CYCLOPS_REPORT_RATE_PER_MIN", "30"))


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path == "/api/reports" and request.method == "POST":
        ip = request.client.host if request.client else "unknown"
        q = _RATE[ip]
        now = time.time()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return JSONResponse({"detail": "Rate limit exceeded for report submission. Retry in a minute."}, status_code=429)
        q.append(now)
    return await call_next(request)


def _check_scenario(s):
    if s not in D.SCENARIOS:
        raise HTTPException(400, f"Unknown scenario '{s}'. Use one of {list(D.SCENARIOS)}")
    return s


def run_meta(scenario):
    return {
        "scenario_id": scenario, "input_version": D.DATA_VERSION, "timestamp": time.time(),
        "model_versions": {"hazard": H.HAZARD_MODEL_VERSION, "asset": A.ASSET_MODEL_VERSION,
                           "cascade": C.CASCADE_MODEL_VERSION, "optimizer": O.OPTIMIZER_VERSION},
    }


def _ints(items):
    return [i.model_dump(exclude_none=True) for i in items]


def _simulate(scenario, interventions=None, forced=None):
    try:
        return C.evaluate(scenario, interventions or [], reports.asset_overrides(), forced or {})
    except (ValueError, KeyError, IndexError) as e:
        raise HTTPException(400, f"Invalid intervention: {e}")


def _serialize(sim, scenario, interventions=None):
    risks = A.asset_risks(scenario)
    G = sim["graph"]
    overrides = reports.asset_overrides()
    nodes = []
    for a in D.ASSETS:
        pop, _ = C.downstream_population(sim, a["id"])
        nodes.append({
            "id": a["id"], "name": a["name"], "type": a["type"], "lat": a["lat"], "lon": a["lon"], "kind": "asset",
            "p": round(sim["p"][a["id"]], 3), "direct": round(sim["direct"][a["id"]], 3),
            "model_direct": risks[a["id"]]["direct_risk"], "field_evidence": overrides.get(a["id"]),
            "active": sim["state"].shelter_active.get(a["id"], True) if a["type"] == "shelter" else True,
            "population_served": pop, "has_generator": a["id"] in sim["state"].generators_at,
            "capacity": a.get("capacity"),
        })
    for v in sim["villages"].values():
        nodes.append({"id": v["id"], "name": v["name"], "type": "village", "kind": "village", "lat": v["lat"],
                      "lon": v["lon"], "p": v["p_degraded"], "pop": v["pop"], "village": v})
    edges = [{"source": u, "target": w, **{k: e[k] for k in ("dependency_type", "strength", "backup", "confidence")}}
             for u, w, e in G.edges(data=True)]
    return {"nodes": nodes, "edges": edges, "metrics": sim["metrics"], "cascade": C.cascade_levels(sim),
            "shelter_load": {k: round(v) for k, v in sim["shelter_load"].items()},
            "iterations": sim["iterations"], "meta": run_meta(scenario),
            "intervention_labels": [O.label(i) for i in (interventions or [])]}


# --- routes ------------------------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "time": time.time()}


@app.get("/api/meta")
def meta():
    return {
        "event": D.EVENT, "scenarios": {k: v["label"] for k, v in D.SCENARIOS.items()},
        "default_resources": D.DEFAULT_RESOURCES, "staging_points": D.STAGING_POINTS,
        "gemini": gemini.status(), "data_version": D.DATA_VERSION,
        "provenance": {
            "track": D.EVENT["provenance"],
            "infrastructure": "SYNTHETIC assets, villages, populations and dependencies placed in the Puri region.",
            "elevation": "SYNTHETIC DEM (replace with SRTM / Copernicus DEM).",
            "field_data": "SYNTHETIC reach snapshot; live reports come from this session.",
            "verification": "SYNTHETIC post-event observations.",
        },
        "coast": D.COAST, "landfall": D.LANDFALL,
    }


@app.get("/api/cyclones")
def cyclones(scenario: str = "expected"):
    _check_scenario(scenario)
    return {"event": D.EVENT, "track": H.track_geojson(scenario), "meta": run_meta(scenario)}


@app.get("/api/hazard")
def hazard(scenario: str = "expected"):
    _check_scenario(scenario)
    return {"cells": H.grid(scenario), "step": D.GRID["step"], "weights": H.WEIGHTS,
            "note": "Explainable proxy model, not a hydrodynamic storm-surge model.", "meta": run_meta(scenario)}


@app.get("/api/assets")
def assets(scenario: str = "expected"):
    _check_scenario(scenario)
    sim = _simulate(scenario)
    risks = A.asset_risks(scenario)
    out = []
    for a in D.ASSETS:
        r = risks[a["id"]]
        pop, vill = C.downstream_population(sim, a["id"])
        deps_up = C.upstream_explanation(sim, a["id"])
        deps_down = [w for w in sim["graph"].successors(a["id"])]
        out.append({**{k: a[k] for k in ("id", "name", "type", "lat", "lon", "vuln")},
                    "elevated": a.get("elevated", False), "capacity": a.get("capacity"),
                    "inactive": a.get("inactive", False), **r,
                    "risk_after_dependencies": round(sim["p"][a["id"]], 3),
                    "risk_label": A.risk_label(sim["p"][a["id"]]),
                    "population_served": pop, "villages_served": vill,
                    "upstream": deps_up, "downstream": deps_down,
                    "field_evidence": reports.asset_overrides().get(a["id"])})
    return {"assets": out, "formula": {
        "exposure": "E = w_wind*wind + w_flood*inundation + w_rain*rain (type-specific weights)",
        "capacity": "c = 0.56 - 0.34*vulnerability", "risk": "p = 1 / (1 + exp(-(E - c) / 0.07))",
        "weights": D.FRAGILITY}, "meta": run_meta(scenario)}


@app.post("/api/simulate")
def simulate(req: SimRequest):
    _check_scenario(req.scenario)
    ints = _ints(req.interventions)
    sim = _simulate(req.scenario, ints, req.forced)
    return _serialize(sim, req.scenario, ints)


@app.get("/api/interventions/candidates")
def intervention_candidates():
    return {"candidates": O.candidates(), "default_resources": D.DEFAULT_RESOURCES,
            "effects": {"generator_backup": C.GENERATOR_BACKUP, "ambulance_health_multiplier": C.MULT_AMBULANCE,
                        "rescue_shelter_multiplier": C.MULT_RESCUE, "portable_telecom_multiplier": C.MULT_PORTABLE_TELECOM}}


@app.post("/api/optimize")
def optimize(req: OptimizeRequest):
    _check_scenario(req.scenario)
    res = {**D.DEFAULT_RESOURCES, **{k: int(v) for k, v in req.resources.items()}}
    if any(v < 0 for v in res.values()):
        raise HTTPException(400, "Resources cannot be negative")
    out = O.optimize(req.scenario, res, _ints(req.interventions), reports.asset_overrides())
    return {**out, "meta": run_meta(req.scenario)}


@app.post("/api/stress-test")
def stress_test():
    forced = {"P04": 1.0, "B17": 1.0, "T07": 1.0}
    sim = _simulate("severe", [], forced)
    opt = O.optimize("severe", D.DEFAULT_RESOURCES, [], reports.asset_overrides(), forced)
    return {"description": "Severe scenario + forced failure of P04, B17 and T07 (compound failure).",
            "forced": forced, "metrics": sim["metrics"], "cascade": C.cascade_levels(sim),
            "plan": opt["plan"], "after": opt["after"],
            "system_still_produced_plan": len(opt["plan"]) > 0, "meta": run_meta("severe")}


@app.post("/api/reach-gap")
def reach_gap(req: SimRequest):
    _check_scenario(req.scenario)
    sim = _simulate(req.scenario, _ints(req.interventions))
    return {**RG.reach_gap(sim, reports.village_report_counts()), "meta": run_meta(req.scenario)}


@app.post("/api/reports")
async def submit_report(text: str = Form(""), lat: float = Form(...), lon: float = Form(...),
                        language: str = Form("en"), client_report_id: str | None = Form(None),
                        contact: str | None = Form(None), captured_at: float | None = Form(None),
                        photo: UploadFile | None = File(None)):
    if not (19.0 <= lat <= 21.5 and 85.0 <= lon <= 87.5):
        raise HTTPException(400, "Location is outside the demo district")
    img, mime = None, None
    if photo is not None and photo.filename:
        img = await photo.read()
        mime = photo.content_type
        if len(img) > MAX_UPLOAD:
            raise HTTPException(413, "Photo too large (max 6 MB)")
        if mime not in ("image/jpeg", "image/png", "image/webp", "image/heic"):
            raise HTTPException(415, "Photo must be JPEG, PNG, WEBP or HEIC")
    if not text and not img:
        raise HTTPException(400, "Provide text or a photo")
    return reports.ingest(text, lat, lon, language, client_report_id, img, mime, contact, captured_at)


@app.get("/api/reports")
def get_reports():
    return {"reports": reports.list_reports(), "overrides": reports.asset_overrides(), "gemini": gemini.status()}


@app.post("/api/reports/{rid}/review")
def review_report(rid: str, req: ReviewRequest):
    try:
        return reports.review(rid, req.decision, req.note)
    except KeyError:
        raise HTTPException(404, "Report not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/verify")
def verify(scenario: str = "expected"):
    _check_scenario(scenario)
    return {**V.verify(scenario), "meta": run_meta(scenario)}


@app.post("/api/verify/memory/{mid}")
def review_memory(mid: str, req: ReviewRequest):
    status = {"approve": "CONFIRMED_ERROR", "reject": "DISMISSED"}.get(req.decision, req.decision)
    try:
        return V.review_memory(mid, status, req.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/alerts")
def alerts(req: AlertRequest):
    _check_scenario(req.scenario)
    sim = _simulate(req.scenario, _ints(req.interventions))
    if req.village_id not in sim["villages"]:
        raise HTTPException(404, "Unknown village")
    return comms.alerts(sim, req.village_id, req.scenario)


@app.post("/api/brief")
def brief(req: BriefRequest):
    _check_scenario(req.scenario)
    ints = _ints(req.interventions)
    sim = _simulate(req.scenario, ints)
    rg = RG.reach_gap(sim, reports.village_report_counts())
    return {**comms.brief(sim, req.scenario, ints, rg, [O.label(i) for i in ints]), "meta": run_meta(req.scenario)}


@app.get("/api/evaluation")
def get_evaluation(scenario: str = "expected"):
    _check_scenario(scenario)
    return {**evaluation.evaluation(scenario), "meta": run_meta(scenario)}


@app.post("/api/evaluation/extraction")
def run_extraction_eval():
    return evaluation.extraction_eval()


@app.post("/api/reset")
def reset():
    reports.reset()
    V.reset()
    return {"ok": True}


# --- frontend ----------------------------------------------------------------------------------------
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")

    @app.get("/sw.js")
    def sw():
        return FileResponse(FRONTEND / "sw.js", media_type="application/javascript")

    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(FRONTEND / "manifest.webmanifest", media_type="application/manifest+json")
