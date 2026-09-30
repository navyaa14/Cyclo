"""
Evaluation. Every block is labelled with its evidence class and they are never mixed:
  HISTORICAL VALIDATION   - not run in this prototype (needs IBTrACS + observed damage labels)
  SYNTHETIC STRESS TEST   - verification against seeded synthetic observations
  SIMULATION COMPARISON   - optimizer vs. no-action baseline inside the same model
  EXTRACTION TEST SET     - 12 hand-labelled text reports (EN/HI/OR) through the live extractor
"""
from __future__ import annotations

from ..engines import optimizer as O
from ..engines import verify as V
from . import reports as R
from . import gemini as G

EXTRACTION_TEST_SET = [
    ("Electric pole fallen across the main road near the temple, wires on the ground", "POWER_INFRASTRUCTURE_DAMAGE", "HIGH"),
    ("Big tree fallen, road completely blocked, cars cannot pass", "ROAD_BLOCKAGE", "HIGH"),
    ("Water flowing over the bridge, railing broken", "BRIDGE_DAMAGE", "HIGH"),
    ("Knee deep water in the lane, houses flooded", "FLOODING", "MEDIUM"),
    ("No mobile network since morning, tower looks bent", "TELECOM_DAMAGE", "HIGH"),
    ("PHC has no electricity, doctor says fridge for vaccines is off", "HEALTH_FACILITY_ISSUE", "HIGH"),
    ("Family of five trapped on roof, water rising", "PEOPLE_STRANDED", "CRITICAL"),
    ("Roof of the school blown away", "BUILDING_DAMAGE", "HIGH"),
    ("बिजली का खंभा गिर गया है, तार सड़क पर पड़े हैं", "POWER_INFRASTRUCTURE_DAMAGE", "HIGH"),
    ("गाँव में बाढ़ का पानी घरों में घुस गया है", "FLOODING", "MEDIUM"),
    ("ରାସ୍ତା ଉପରେ ଗଛ ପଡିଛି, ରାସ୍ତା ବନ୍ଦ", "ROAD_BLOCKAGE", "HIGH"),
    ("ପୋଲ ଉପରେ ପାଣି ବହୁଛି", "BRIDGE_DAMAGE", "HIGH"),
]


def extraction_eval():
    n = len(EXTRACTION_TEST_SET)
    ok_schema = type_ok = sev_ok = 0
    rows = []
    for text, exp_type, exp_sev in EXTRACTION_TEST_SET:
        ex, meta = R.extract(text, None, None)
        if ex:
            ok_schema += 1
            t_ok = ex["incident_type"] == exp_type
            s_ok = ex["estimated_severity"] == exp_sev
            type_ok += t_ok
            sev_ok += s_ok
            rows.append({"text": text, "expected": exp_type, "got": ex["incident_type"], "type_ok": t_ok,
                         "severity_expected": exp_sev, "severity_got": ex["estimated_severity"]})
        else:
            rows.append({"text": text, "expected": exp_type, "got": None, "type_ok": False, "error": meta.get("error")})
    return {
        "label": "Extraction test set (12 hand-labelled text reports, English/Hindi/Odia; tiny, indicative only)",
        "caveat": None if G.enabled() else "The fallback keyword rules were written alongside this test set, so this score does not measure generalisation. Configure Gemini to evaluate the real extractor.",
        "extractor": G.MODEL if G.enabled() else "rule-based fallback (no Gemini credentials)",
        "n": n, "structured_output_success_rate": round(ok_schema / n, 3),
        "incident_type_accuracy": round(type_ok / n, 3), "severity_agreement": round(sev_ok / n, 3),
        "rows": rows,
    }


def evaluation(scenario="expected"):
    ver = V.verify(scenario)
    opt = O.optimize(scenario)
    b, a = opt["before"], opt["after"]
    return {
        "historical_validation": {
            "label": "Historical validation",
            "status": "Not run in this prototype",
            "why": "Requires IBTrACS tracks for several past Odisha cyclones plus observed asset-damage labels "
                   "(utility outage logs, OSDMA damage assessments). The IBTrACS adapter is included; labels are not.",
        },
        "synthetic_stress_test": {
            "label": "Synthetic stress test (seeded synthetic observations, not real outcomes)",
            "flood_extent": {k: ver["flood"][k] for k in ("iou", "precision", "recall", "tp", "fp", "fn")},
            "asset_disruption": {"confusion": ver["assets"]["confusion"], "brier": ver["assets"]["brier"],
                                 "calibration": ver["assets"]["calibration"], "threshold": 0.5},
        },
        "simulation_comparison": {
            "label": "Simulation comparison (same model, no-action baseline vs greedy plan)",
            "algorithm": opt["algorithm"],
            "rows": [
                {"metric": "Expected residents with degraded access", "baseline": b["expected_degraded_pop"], "optimized": a["expected_degraded_pop"]},
                {"metric": "Expected residents without robust shelter route", "baseline": b["expected_without_shelter_route"], "optimized": a["expected_without_shelter_route"]},
                {"metric": "Expected residents losing health access", "baseline": b["expected_health_access_loss"], "optimized": a["expected_health_access_loss"]},
                {"metric": "Critical assets disrupted (p >= 0.5)", "baseline": b["critical_assets_disrupted"], "optimized": a["critical_assets_disrupted"]},
                {"metric": "PHCs at severe risk", "baseline": b["phcs_severe_risk"], "optimized": a["phcs_severe_risk"]},
                {"metric": "Resilience score", "baseline": b["resilience_score"], "optimized": a["resilience_score"]},
            ],
            "caveat": "This measures improvement inside the model's own assumptions, not real-world effectiveness.",
        },
        "extraction": {"label": "Extraction test set", "status": "Run on demand (POST /api/evaluation/extraction)"},
    }
