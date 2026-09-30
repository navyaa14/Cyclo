"""
Multilingual warnings + incident brief.

Rule: every fact comes from structured system state. Gemini only rewrites. Any generated output that
contains a number not present in the facts is rejected and the deterministic template is used instead.
Fallback Hindi/Odia templates should be reviewed by native speakers / OSDMA before real use.
"""
from __future__ import annotations

import json
import time

from ..data import demo_scenario as D
from ..engines import assets as A
from . import gemini as G


def _route_text(route):
    return " + ".join(route) if route else "local road"


def _route_risk(sim, route):
    surv = 1.0
    for a in route:
        surv *= 1 - sim["p"][a]
    return 1 - surv


def alert_facts(sim, village_id, scenario):
    """Pick the safest ACTIVE shelter option (assigned route or modelled alternative) so a warning
    never tells people to travel over an asset it also tells them to avoid."""
    v = sim["villages"][village_id]
    vdef = sim["state"].villages[village_id]
    options = [vdef["shelter"]] + vdef.get("alts", [])
    options = [o for o in options if sim["state"].shelter_active.get(o["shelter"], True)]
    best = min(options, key=lambda o: _route_risk(sim, o["route"]))
    route_risk = _route_risk(sim, best["route"])
    high = sorted({a for a in (v["shelter_route"] + v["health_route"] + best["route"]) if sim["p"][a] >= 0.5})
    level = "RED" if v["p_degraded"] >= 0.6 else "ORANGE" if v["p_degraded"] >= 0.3 else "YELLOW"
    return {
        "area": v["name"], "event": D.EVENT["name"], "landfall": D.EVENT["landfall_label"],
        "warning_level": level, "shelter": best["shelter"], "route": _route_text(best["route"]),
        "route_changed_from_plan": best["shelter"] != v["shelter"] or best["route"] != v["shelter_route"],
        "safe_route_available": route_risk < 0.5,
        "avoid": [a for a in high if a not in best["route"]],
        "nearest_health_facility": v["phc"], "emergency_number": D.EMERGENCY_NUMBER,
    }


def template_alerts(f):
    avoid_en = f" Avoid {', '.join(f['avoid'])}." if f["avoid"] else ""
    if not f["safe_route_available"]:
        return {
            "official_en": (f"{f['warning_level']} warning for {f['area']} ({f['event']}, landfall {f['landfall']}). "
                            f"No evacuation route to a shelter is currently assessed as safe. Assisted evacuation or "
                            f"shelter-in-place decision required from the control room. Emergency: {f['emergency_number']}."),
            "citizen_en": (f"Cyclone warning for {f['area']}. Roads to the shelter may be unsafe. "
                           f"Wait for instructions from officials. Call {f['emergency_number']} for help."),
            "hi": (f"चक्रवात चेतावनी: {f['area']} में आश्रय तक के रास्ते असुरक्षित हो सकते हैं। "
                   f"अधिकारियों के निर्देश की प्रतीक्षा करें। सहायता के लिए {f['emergency_number']} पर कॉल करें।"),
            "or": (f"ଘୂର୍ଣ୍ଣିବାତ୍ୟା ସତର୍କତା: {f['area']}ରୁ ଆଶ୍ରୟସ୍ଥଳୀ ଯିବା ରାସ୍ତା ବିପଦପୂର୍ଣ୍ଣ ହୋଇପାରେ। "
                   f"ଅଧିକାରୀଙ୍କ ନିର୍ଦ୍ଦେଶକୁ ଅପେକ୍ଷା କରନ୍ତୁ। ସହାୟତା ପାଇଁ {f['emergency_number']}କୁ କଲ କରନ୍ତୁ।"),
            "voice_en": f"Cyclone warning. {f['area']}. Roads may be unsafe. Wait for official instructions. Call {f['emergency_number']}.",
        }
    return {
        "official_en": (f"{f['warning_level']} warning for {f['area']} ({f['event']}, landfall {f['landfall']}). "
                        f"Evacuate to shelter {f['shelter']} via {f['route']}.{avoid_en} "
                        + ("This differs from the standing evacuation plan. " if f["route_changed_from_plan"] else "")
                        + f"Nearest health facility: {f['nearest_health_facility']}. Emergency: {f['emergency_number']}."),
        "citizen_en": (f"Cyclone warning for {f['area']}. Strong wind and flooding expected. "
                       f"Go to shelter {f['shelter']} using {f['route']}.{avoid_en} Call {f['emergency_number']} for help."),
        "hi": (f"चक्रवात चेतावनी: {f['area']} में तेज़ हवा और जलभराव का खतरा है। "
               f"सुरक्षित आश्रय {f['shelter']} जाएँ, मार्ग: {f['route']}। "
               + (f"{', '.join(f['avoid'])} से न जाएँ। " if f["avoid"] else "")
               + f"सहायता के लिए {f['emergency_number']} पर कॉल करें।"),
        "or": (f"ଘୂର୍ଣ୍ଣିବାତ୍ୟା ସତର୍କତା: {f['area']}ରେ ପ୍ରବଳ ପବନ ଓ ଜଳବନ୍ଦୀ ହେବାର ଆଶଙ୍କା। "
               f"ଆଶ୍ରୟସ୍ଥଳୀ {f['shelter']}କୁ ଯାଆନ୍ତୁ, ରାସ୍ତା: {f['route']}। "
               + (f"{', '.join(f['avoid'])} ଦେଇ ଯାଆନ୍ତୁ ନାହିଁ। " if f["avoid"] else "")
               + f"ସହାୟତା ପାଇଁ {f['emergency_number']}କୁ କଲ କରନ୍ତୁ।"),
        "voice_en": (f"Cyclone warning. {f['area']}. Go to shelter {f['shelter']} now. "
                     f"Use {f['route']}. Call {f['emergency_number']}."),
    }


ALERT_PROMPT = """Rewrite these VERIFIED facts into five cyclone warning messages. Return JSON with keys
official_en, citizen_en (simple English, low literacy), hi (Hindi), or (Odia), voice_en (under 25 words, for IVR/radio).
Use ONLY these facts. Do not add numbers, times, wind speeds, casualties or instructions that are not in the facts.
Keep asset codes exactly as written.
FACTS: {facts}"""


def alerts(sim, village_id, scenario):
    f = alert_facts(sim, village_id, scenario)
    facts_text = json.dumps(f, ensure_ascii=False)
    base = {"facts": f, "generated_at": time.time(), "review_required": True}
    if G.enabled():
        try:
            from pydantic import BaseModel

            class AlertOut(BaseModel):
                official_en: str
                citizen_en: str
                hi: str
                or_: str | None = None
                voice_en: str

            raw = G.generate_json(ALERT_PROMPT.format(facts=facts_text), {
                "type": "OBJECT", "properties": {k: {"type": "STRING"} for k in
                                                 ["official_en", "citizen_en", "hi", "or", "voice_en"]},
                "required": ["official_en", "citizen_en", "hi", "or", "voice_en"]})
            out = json.loads(raw)
            ok, extra = G.numbers_grounded(" ".join(out.values()), facts_text)
            if ok and all(k in out for k in ["official_en", "citizen_en", "hi", "or", "voice_en"]):
                return {**base, "messages": out, "source": f"Gemini ({G.MODEL}), grounding check passed"}
            return {**base, "messages": template_alerts(f),
                    "source": f"Template (Gemini output rejected: ungrounded numbers {extra})"}
        except Exception as e:
            return {**base, "messages": template_alerts(f), "source": f"Template (Gemini error: {e})"}
    return {**base, "messages": template_alerts(f), "source": "Template (no Gemini credentials configured)"}


def brief_facts(sim, scenario, interventions, reach, plan_labels):
    risks = A.asset_risks(scenario)
    top = sorted(((a["id"], a["name"], sim["p"][a["id"]], risks[a["id"]]["direct_risk"]) for a in D.ASSETS
                  if not a.get("inactive")), key=lambda x: -x[2])[:6]
    m = sim["metrics"]
    return {
        "event": D.EVENT["name"], "district": D.EVENT["district"], "landfall": D.EVENT["landfall_label"],
        "scenario": D.SCENARIOS[scenario]["label"],
        "metrics": {k: v for k, v in m.items() if k != "resilience_formula"},
        "highest_risk_assets": [{"id": i, "name": n, "disruption_probability_pct": round(p * 100),
                                 "direct_risk_pct": round(d * 100)} for i, n, p, d in top],
        "cascading_risks": sorted([{"asset": a["id"], "direct_pct": round(sim["direct"][a["id"]] * 100),
                                    "after_dependencies_pct": round(sim["p"][a["id"]] * 100)}
                                   for a in D.ASSETS if not a.get("inactive")
                                   and sim["p"][a["id"]] - sim["direct"][a["id"]] >= 0.1],
                                  key=lambda c: c["direct_pct"] - c["after_dependencies_pct"]),
        "applied_actions": plan_labels,
        "possible_coverage_gaps": [{"area": r["name"], "predicted_affected": r["predicted_affected"],
                                    "observed": r["observed"]} for r in reach["villages"]
                                   if r["status"] == "POSSIBLE BLIND SPOT"],
        "data_freshness": "Replay scenario; synthetic infrastructure and field data.",
    }


def template_brief(f):
    m = f["metrics"]
    L = [f"# Incident brief: {f['event']}", f"District: {f['district']}. Scenario: {f['scenario']}.", "",
         "## Situation", f"Landfall {f['landfall']}. Resilience score {m['resilience_score']} of 100.", "",
         "## Expected impact",
         f"- Critical assets likely disrupted: {m['critical_assets_disrupted']}",
         f"- PHCs at severe risk: {m['phcs_severe_risk']}",
         f"- Expected residents with degraded access to health care or shelter: {m['expected_degraded_pop']:,}",
         f"- Expected residents without a robust shelter route: {m['expected_without_shelter_route']:,}", "",
         "## Highest-risk assets"]
    L += [f"- {a['name']} ({a['id']}): {a['disruption_probability_pct']}% disruption probability" for a in f["highest_risk_assets"]]
    L += ["", "## Cascading risks"]
    L += [f"- {c['asset']}: direct {c['direct_pct']}%, rising to {c['after_dependencies_pct']}% through dependencies"
          for c in f["cascading_risks"]] or ["- None above reporting threshold."]
    L += ["", "## Recommended / applied actions"]
    L += [f"- {a}" for a in f["applied_actions"]] or ["- No actions applied yet. Run Find best plan in the Action lab."]
    L += ["", "## Possible coverage gaps (require verification)"]
    L += [f"- {g['area']}: ~{g['predicted_affected']:,} predicted affected, {g['observed']:,} observed"
          for g in f["possible_coverage_gaps"]] or ["- None flagged."]
    L += ["", "## Confidence and uncertainty",
          "Probabilities come from a hazard proxy and fragility curves, not a hydrodynamic surge model. "
          "Population figures are expected values. Switch scenario (Low / Expected / High) to see the range.",
          "", "## Data freshness", f["data_freshness"]]
    return "\n".join(L)


BRIEF_PROMPT = """Write a one-page official incident brief in Markdown for a district emergency operations centre.
Sections: Situation; Expected impact; Highest-risk assets; Cascading risks; Recommended actions;
Possible coverage gaps (say they require verification); Confidence and uncertainty; Data freshness.
Use ONLY the facts below. Do not invent any number, time, place or instruction. Keep it concise.
FACTS: {facts}"""


def brief(sim, scenario, interventions, reach, plan_labels):
    f = brief_facts(sim, scenario, interventions, reach, plan_labels)
    facts_text = json.dumps(f, ensure_ascii=False) + " " + template_brief(f)
    base = {"facts": f, "generated_at": time.time()}
    if G.enabled():
        try:
            text = G.generate_text(BRIEF_PROMPT.format(facts=json.dumps(f, ensure_ascii=False)))
            ok, extra = G.numbers_grounded(text, facts_text)
            if ok and text.strip():
                return {**base, "markdown": text, "source": f"Gemini ({G.MODEL}), grounding check passed"}
            return {**base, "markdown": template_brief(f),
                    "source": f"Template (Gemini output rejected: ungrounded numbers {extra[:6]})"}
        except Exception as e:
            return {**base, "markdown": template_brief(f), "source": f"Template (Gemini error: {e})"}
    return {**base, "markdown": template_brief(f), "source": "Template (no Gemini credentials configured)"}
