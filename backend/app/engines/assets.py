"""
Infrastructure vulnerability engine.

Exposure  E = w_wind*wind + w_flood*inundation + w_rain*rain      (type-specific fragility weights)
Capacity  c = 0.56 - 0.34*vulnerability                            (fragile assets fail at lower exposure)
Risk      p = logistic((E - c) / 0.07)                             (fragility-curve style, bounded in [0,1])

Contributions shown in the evidence drawer are the ACTUAL shares of each weighted term in E.
"""
from __future__ import annotations

from functools import lru_cache
import math

from ..data import demo_scenario as D
from . import hazard as H

ASSET_MODEL_VERSION = "fragility-logistic-0.2"
ASSET_INDEX = {a["id"]: a for a in D.ASSETS}


def fragility_risk(exposure: float, vuln: float) -> float:
    cap = 0.56 - 0.34 * vuln
    return 1.0 / (1.0 + math.exp(-(exposure - cap) / 0.07))


def _risk_for(asset, hz, i):
    ww, wf, wr = D.FRAGILITY[asset["type"]]
    terms = {"wind": ww * float(hz["wind"][i]), "inundation": wf * float(hz["inundation"][i]),
             "rain": wr * float(hz["rain"][i])}
    exposure = sum(terms.values())
    return exposure, terms, fragility_risk(exposure, asset["vuln"])


@lru_cache(maxsize=8)
def _asset_risks(scenario: str):
    lat = [a["lat"] for a in D.ASSETS]
    lon = [a["lon"] for a in D.ASSETS]
    plinth = [a.get("plinth_m", 0.0) for a in D.ASSETS]
    out = {}
    per = {s: H.hazard_components(lat, lon, s, plinth) for s in ("conservative", "expected", "severe")}
    for i, a in enumerate(D.ASSETS):
        exposure, terms, risk = _risk_for(a, per[scenario], i)
        _, _, lo = _risk_for(a, per["conservative"], i)
        _, _, hi = _risk_for(a, per["severe"], i)
        hz = per[scenario]
        total = sum(terms.values()) or 1e-9
        contributions = sorted(
            [{"factor": {"wind": "Wind exposure", "inundation": "Inundation / surge exposure",
                         "rain": "Rainfall exposure"}[k], "share": round(v / total, 3)} for k, v in terms.items()],
            key=lambda c: -c["share"])
        out[a["id"]] = {
            "direct_risk": round(risk, 3),
            "risk_low": round(min(lo, risk, hi), 3), "risk_high": round(max(lo, risk, hi), 3),
            "exposure": round(exposure, 3),
            "capacity_threshold": round(0.56 - 0.34 * a["vuln"], 3),
            "vulnerability": a["vuln"],
            "hazard": {"wind": round(float(hz["wind"][i]), 3), "rain": round(float(hz["rain"][i]), 3),
                       "inundation": round(float(hz["inundation"][i]), 3)},
            "physical": {"wind_kmh": round(float(hz["wind_kmh"][i])), "rain_mm": round(float(hz["rain_mm"][i])),
                         "surge_depth_m": round(float(hz["surge_depth_m"][i]), 2),
                         "elevation_m": round(float(hz["elevation_m"][i]), 1),
                         "coast_km": round(float(hz["coast_km"][i]), 1)},
            "contributions": contributions,
            "confidence": round(max(0.35, min(0.95, 1 - 1.2 * (max(lo, hi) - min(lo, hi)))), 2),
        }
    return out


def asset_risks(scenario: str = "expected"):
    return _asset_risks(scenario)


def risk_label(p: float) -> str:
    if p >= 0.7:
        return "Very high"
    if p >= 0.5:
        return "High"
    if p >= 0.3:
        return "Moderate"
    return "Low"
