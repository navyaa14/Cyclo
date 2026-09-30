"""
Field / citizen report pipeline.

photo | voice-transcript | text  ->  Gemini (structured JSON, schema-constrained)
                                 ->  Pydantic validation  (invalid -> NEEDS_REVIEW, never enters graph)
                                 ->  idempotency (client_report_id) + near-duplicate clustering
                                 ->  link to nearest matching asset + village
                                 ->  graph override (pending: weight 0.7, approved: 1.0, rejected: 0)
"""
from __future__ import annotations

import json
import math
import threading
import time
import uuid

from pydantic import ValidationError

from ..data import demo_scenario as D
from ..schemas import IncidentExtraction
from . import gemini as G

LOCK = threading.RLock()
REPORTS: dict[str, dict] = {}
BY_CLIENT_ID: dict[str, str] = {}

INCIDENT_TO_ASSET_TYPES = {
    "POWER_INFRASTRUCTURE_DAMAGE": ["substation", "pump"],
    "ROAD_BLOCKAGE": ["road", "bridge"],
    "BRIDGE_DAMAGE": ["bridge"],
    "FLOODING": ["road", "bridge"],
    "TELECOM_DAMAGE": ["telecom"],
    "HEALTH_FACILITY_ISSUE": ["phc"],
}
SEVERITY_WEIGHT = {"LOW": 0.35, "MEDIUM": 0.6, "HIGH": 0.85, "CRITICAL": 1.0}
LINK_RADIUS_KM = 3.0
DEDUP_RADIUS_KM = 0.5
DEDUP_WINDOW_S = 2 * 3600

EXTRACTION_PROMPT = """You are a disaster field-report extraction component for a district emergency
operations centre. Extract ONLY what is visible in the image or stated in the text. Do not guess
locations, casualties or numbers. If unsure, lower confidence and set requires_human_review=true.
The report may be in English, Hindi or Odia; write summary_en in plain English.
Report text: {text}
"""


def km(lat1, lon1, lat2, lon2):
    return math.hypot((lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2)), (lat2 - lat1) * 111.0)


# --- Fallback extractor: transparent keyword rules, used only when Gemini is not configured -----------
KEYWORDS = [
    ("POWER_INFRASTRUCTURE_DAMAGE", ["pole", "electric", "power", "wire", "transformer", "substation", "बिजली", "खंभा", "ବିଦ୍ୟୁତ", "ଖୁଣ୍ଟ"]),
    ("BRIDGE_DAMAGE", ["bridge", "पुल", "ପୋଲ"]),
    ("TELECOM_DAMAGE", ["tower", "network", "signal", "mobile", "टावर", "नेटवर्क", "ଟାୱାର"]),
    ("HEALTH_FACILITY_ISSUE", ["phc", "hospital", "clinic", "doctor", "अस्पताल", "ଡାକ୍ତରଖାନା"]),
    ("PEOPLE_STRANDED", ["stranded", "trapped", "rescue", "फंसे", "ଫସି"]),
    ("FLOODING", ["flood", "water", "submerged", "पानी", "बाढ़", "ପାଣି", "ବନ୍ୟା"]),
    ("ROAD_BLOCKAGE", ["road", "tree", "blocked", "सड़क", "पेड़", "ରାସ୍ତା", "ଗଛ"]),
    ("BUILDING_DAMAGE", ["house", "roof", "wall", "building", "घर", "छत", "ଘର"]),
]


def fallback_extract(text: str) -> dict:
    t = (text or "").lower()
    found = [k for k, words in KEYWORDS if any(w in t for w in words)]
    itype = found[0] if found else "OTHER"
    sev = "HIGH" if any(w in t for w in ["collapsed", "fallen", "blocked", "trapped", "severe", "गिर", "ବନ୍ଦ"]) else "MEDIUM"
    return {
        "incident_type": itype,
        "objects": [],
        "road_blocked": any(w in t for w in ["blocked", "tree", "बंद", "ବନ୍ଦ"]),
        "estimated_severity": sev,
        "visible_flooding": "FLOODING" in found,
        "people_at_risk": "PEOPLE_STRANDED" in found,
        "summary_en": (text or "")[:200] or "No text provided.",
        "confidence": 0.5 if found else 0.2,
        "requires_human_review": True,
    }


def extract(text: str, image: bytes | None, mime: str | None):
    """Returns (extraction_dict | None, meta). Never raises into the caller."""
    meta = {"model": None, "validation": None, "raw": None, "error": None}
    if G.enabled():
        meta["model"] = G.MODEL
        try:
            raw = G.generate_json(EXTRACTION_PROMPT.format(text=text or "(none)"), IncidentExtraction, image, mime)
            meta["raw"] = raw
        except Exception as e:
            meta["error"] = f"Gemini call failed: {e}"
            return None, meta
    else:
        meta["model"] = "rule-based fallback (no Gemini credentials; photo not analysed)"
        raw = json.dumps(fallback_extract(text))
        meta["raw"] = raw
    return validate_extraction(raw, meta)


def validate_extraction(raw: str, meta: dict):
    try:
        obj = IncidentExtraction.model_validate_json(raw)
        meta["validation"] = "passed"
        d = obj.model_dump(mode="json")
        d["requires_human_review"] = True  # operational rule: every citizen report is reviewed
        return d, meta
    except ValidationError as e:
        meta["validation"] = "failed"
        meta["error"] = f"Schema validation failed: {e.error_count()} error(s)"
        return None, meta


def _nearest(items, lat, lon, types=None, radius=None):
    best = None
    for it in items:
        if types and it.get("type") not in types:
            continue
        if it.get("inactive"):
            continue
        d = km(lat, lon, it["lat"], it["lon"])
        if (radius is None or d <= radius) and (best is None or d < best[0]):
            best = (d, it)
    return best


def ingest(text: str, lat: float, lon: float, language: str, client_report_id: str | None,
           image: bytes | None = None, mime: str | None = None, contact: str | None = None,
           captured_at: float | None = None):
    with LOCK:
        if client_report_id and client_report_id in BY_CLIENT_ID:
            existing = REPORTS[BY_CLIENT_ID[client_report_id]]
            return {**existing, "idempotent_replay": True}

    extraction, meta = extract(text, image, mime)
    now = time.time()
    rid = "R-" + uuid.uuid4().hex[:8].upper()
    rep = {
        "id": rid, "client_report_id": client_report_id, "received_at": now,
        "captured_at": captured_at or now, "lat": lat, "lon": lon, "language": language,
        "text": (text or "")[:1000], "has_photo": bool(image), "contact_provided": bool(contact),
        "extraction": extraction, "extraction_meta": {k: v for k, v in meta.items() if k != "raw"},
        "status": "PENDING_REVIEW" if extraction else "NEEDS_REVIEW_INVALID_AI_OUTPUT",
        "linked_asset": None, "linked_village": None, "cluster_id": None, "duplicate_of": None,
    }
    if extraction:
        types_ = INCIDENT_TO_ASSET_TYPES.get(extraction["incident_type"])
        if types_:
            n = _nearest(D.ASSETS, lat, lon, types_, LINK_RADIUS_KM)
            if n:
                rep["linked_asset"] = {"id": n[1]["id"], "distance_km": round(n[0], 2)}
    v = _nearest(D.VILLAGES, lat, lon, None, 5.0)
    if v:
        rep["linked_village"] = v[1]["id"]

    with LOCK:
        if client_report_id and client_report_id in BY_CLIENT_ID:  # race: second writer loses
            return {**REPORTS[BY_CLIENT_ID[client_report_id]], "idempotent_replay": True}
        if extraction:
            for other in REPORTS.values():
                oe = other.get("extraction")
                if (oe and oe["incident_type"] == extraction["incident_type"]
                        and abs(other["captured_at"] - rep["captured_at"]) <= DEDUP_WINDOW_S
                        and km(lat, lon, other["lat"], other["lon"]) <= DEDUP_RADIUS_KM):
                    rep["cluster_id"] = other["cluster_id"] or other["id"]
                    rep["duplicate_of"] = other["id"]
                    other["cluster_id"] = rep["cluster_id"]
                    break
        REPORTS[rid] = rep
        if client_report_id:
            BY_CLIENT_ID[client_report_id] = rid
    return rep


def review(rid: str, decision: str, note: str | None = None):
    with LOCK:
        rep = REPORTS.get(rid)
        if not rep:
            raise KeyError(rid)
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        if decision == "approve" and not rep["extraction"]:
            raise ValueError("Cannot approve a report without a valid structured extraction")
        rep["status"] = "APPROVED" if decision == "approve" else "REJECTED"
        rep["review_note"] = note
        rep["reviewed_at"] = time.time()
        return rep


def asset_overrides() -> dict:
    """Minimum direct-disruption probabilities implied by field evidence (one per cluster)."""
    out = {}
    with LOCK:
        for rep in REPORTS.values():
            ex = rep.get("extraction")
            if not ex or not rep.get("linked_asset") or rep["status"] == "REJECTED" or rep.get("duplicate_of"):
                continue
            sev = SEVERITY_WEIGHT[ex["estimated_severity"]]
            # approved = human-verified observed damage; pending = discounted by review status and AI confidence
            val = sev if rep["status"] == "APPROVED" else 0.7 * sev * (0.5 + 0.5 * ex["confidence"])
            aid = rep["linked_asset"]["id"]
            out[aid] = max(out.get(aid, 0.0), round(val, 3))
    return out


def village_report_counts() -> dict:
    out = {}
    with LOCK:
        for rep in REPORTS.values():
            if rep.get("linked_village") and rep["status"] != "REJECTED" and not rep.get("duplicate_of"):
                out[rep["linked_village"]] = out.get(rep["linked_village"], 0) + 1
    return out


def list_reports():
    with LOCK:
        return sorted(REPORTS.values(), key=lambda r: -r["received_at"])


def reset():
    with LOCK:
        REPORTS.clear()
        BY_CLIENT_ID.clear()
