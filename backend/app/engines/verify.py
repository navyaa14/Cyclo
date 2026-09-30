"""
Post-event verification + failure memory.

OBSERVED DATA IN THIS DEMO IS SYNTHETIC. It is generated deterministically (seeded) from the expected
hazard field plus noise, with a few scripted outcomes, to exercise the verification workflow.
It is NOT real Cyclone Fani damage data. In production the observed flood extent comes from
Sentinel-1 SAR change detection (see docs/earth_engine_sentinel1_flood.js) and asset outcomes come
from approved field reports and utility outage logs.
"""
from __future__ import annotations

import threading
import numpy as np

from ..data import demo_scenario as D
from . import assets as A
from . import hazard as H

VERIFY_VERSION = "verify-0.2"
_LOCK = threading.RLock()
_MEMORY_REVIEW: dict[str, dict] = {}

# Scripted outcomes (synthetic) so the demo shows both a hit and a false positive.
SCRIPTED = {"R21": False, "B17": True, "P04": True, "T08": True, "PHC-7": False, "R12": True}


def observed_flood(scenario="expected", seed=7):
    cells = H.grid(scenario)
    rng = np.random.default_rng(seed)
    lat = np.array([c["lat"] for c in cells])
    lon = np.array([c["lon"] for c in cells])
    pred = np.array([c["inundation_risk"] for c in cells])
    noise = rng.normal(0, 0.12, len(cells))
    chan = H.channel_factor(lat, lon)
    obs = (pred + noise + 0.25 * chan) > 0.5
    base_water = chan > 0.6
    return cells, pred >= 0.5, obs, base_water


def observed_assets(scenario="expected", seed=11):
    risks = A.asset_risks(scenario)
    rng = np.random.default_rng(seed)
    out = {}
    for a in D.ASSETS:
        if a.get("inactive"):
            continue
        r = risks[a["id"]]["direct_risk"]
        out[a["id"]] = SCRIPTED.get(a["id"], bool(rng.random() < r))
    return out


def _reason(asset, predicted_disrupted, observed):
    if predicted_disrupted and not observed:
        if asset.get("elevated"):
            return "Asset is on an elevated structure; the flood proxy uses ground elevation and ignores deck/embankment height."
        if asset["type"] == "phc":
            return "Direct fragility may be overstated for a building with a raised plinth; check plinth survey data."
        return "Possible over-estimate of local exposure or fragility; needs field check."
    if observed and not predicted_disrupted:
        return "Hazard or fragility under-estimated; check local drainage, tree-fall and asset age."
    return ""


def verify(scenario="expected"):
    cells, pred_f, obs_f, base = observed_flood(scenario)
    tp = int((pred_f & obs_f).sum()); fp = int((pred_f & ~obs_f).sum()); fn = int((~pred_f & obs_f).sum())
    iou = tp / max(1, tp + fp + fn)
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)

    risks = A.asset_risks(scenario)
    obs_a = observed_assets(scenario)
    rows, memory = [], []
    y, pr = [], []
    cm = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for a in D.ASSETS:
        if a["id"] not in obs_a:
            continue
        p = risks[a["id"]]["direct_risk"]
        pd_ = p >= 0.5
        o = obs_a[a["id"]]
        y.append(1.0 if o else 0.0); pr.append(p)
        key = "tp" if pd_ and o else "fp" if pd_ and not o else "fn" if o else "tn"
        cm[key] += 1
        result = {"tp": "CONFIRMED", "fp": "FALSE POSITIVE", "fn": "MISSED", "tn": "CORRECT (no disruption)"}[key]
        rows.append({"asset_id": a["id"], "name": a["name"], "type": a["type"], "predicted_risk": p,
                     "observed": "disrupted" if o else "operational", "result": result})
        if key in ("fp", "fn"):
            mid = f"FM-{a['id']}"
            with _LOCK:
                rv = _MEMORY_REVIEW.get(mid, {"review_status": "PENDING"})
            memory.append({
                "id": mid, "event": D.EVENT["id"], "asset_id": a["id"],
                "prediction": f"disruption risk {p:.0%}", "observation": "disrupted" if o else "operational",
                "error_type": "FALSE_POSITIVE" if key == "fp" else "FALSE_NEGATIVE",
                "possible_reason": _reason(a, pd_, o), **rv,
            })
    y, pr = np.array(y), np.array(pr)
    brier = float(np.mean((pr - y) ** 2))
    bins = []
    edges = [0, 0.2, 0.4, 0.6, 0.8, 1.0001]
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (pr >= lo) & (pr < hi)
        if m.any():
            bins.append({"bin": f"{lo:.1f}-{min(hi, 1):.1f}", "n": int(m.sum()),
                         "mean_predicted": round(float(pr[m].mean()), 3), "observed_rate": round(float(y[m].mean()), 3)})

    learned = []
    for m in memory:
        a = A.ASSET_INDEX[m["asset_id"]]
        if m["error_type"] == "FALSE_POSITIVE" and a.get("elevated"):
            learned.append(f"The flood proxy overestimated disruption for elevated road segments ({a['id']}). Add structure height from road inventory before the next season.")
        elif m["error_type"] == "FALSE_POSITIVE":
            learned.append(f"{a['id']} ({a['type']}) was predicted disrupted but stayed operational. Review its fragility parameters with the asset owner.")
        else:
            learned.append(f"{a['id']} ({a['type']}) was disrupted but predicted below 50%. Check for missing local hazard drivers.")

    step = D.GRID["step"]
    return {
        "verify_version": VERIFY_VERSION,
        "data_label": "SYNTHETIC post-event observations (seeded). Not real Cyclone Fani damage data.",
        "flood": {
            "iou": round(iou, 3), "precision": round(prec, 3), "recall": round(rec, 3),
            "tp": tp, "fp": fp, "fn": fn, "cell_step_deg": step,
            "cells": [{"lat": c["lat"], "lon": c["lon"], "pred": bool(pf), "obs": bool(of), "base": bool(bw)}
                      for c, pf, of, bw in zip(cells, pred_f, obs_f, base)],
        },
        "assets": {"rows": sorted(rows, key=lambda r: r["result"]), "confusion": cm,
                   "brier": round(brier, 3), "calibration": bins, "threshold": 0.5},
        "failure_memory": memory,
        "learned": learned,
        "workflow": "observe -> verify -> store -> review -> retrain later (no automatic retraining from unverified data)",
    }


def review_memory(mid: str, status: str, note: str | None = None):
    if status not in ("CONFIRMED_ERROR", "DISMISSED", "PENDING"):
        raise ValueError("status must be CONFIRMED_ERROR, DISMISSED or PENDING")
    with _LOCK:
        _MEMORY_REVIEW[mid] = {"review_status": status, "review_note": note}
        return _MEMORY_REVIEW[mid]


def reset():
    with _LOCK:
        _MEMORY_REVIEW.clear()
