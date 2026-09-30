"""
Reach-gap detector: predicted-affected population vs. what the response picture has actually observed.

predicted_affected = population x P(degraded access)            (from the cascade simulation)
observed           = verified contacts + shelter check-ins     (synthetic snapshot + live reports)
coverage           = observed / predicted_affected

Status rules (a prioritisation signal, NOT proof of harm):
  REACHED              coverage >= 0.50
  PARTIALLY OBSERVED   0.15 <= coverage < 0.50
  POSSIBLE BLIND SPOT  coverage < 0.15 AND (comms-loss risk >= 0.5 OR last contact >= 4 h)
  UNVERIFIED           coverage < 0.15 otherwise
"""
from __future__ import annotations

from ..data import demo_scenario as D

REACH_VERSION = "reach-gap-0.2"


def classify(coverage, comms_loss, last_contact_h):
    if coverage >= 0.5:
        return "REACHED"
    if coverage >= 0.15:
        return "PARTIALLY OBSERVED"
    if comms_loss >= 0.5 or last_contact_h >= 4:
        return "POSSIBLE BLIND SPOT"
    return "UNVERIFIED"


def reach_gap(sim_result, live_report_counts: dict | None = None):
    live = live_report_counts or {}
    rows = []
    for vid, v in sim_result["villages"].items():
        snap = D.FIELD_SNAPSHOT.get(vid, {"reports": 0, "verified_contacts": 0, "shelter_checkins": 0, "last_contact_h": 99})
        predicted = max(1, round(v["pop"] * v["p_degraded"]))
        observed = snap["verified_contacts"] + snap["shelter_checkins"]
        coverage = min(1.0, observed / predicted)
        reports = snap["reports"] + live.get(vid, 0)
        last_h = 0.0 if live.get(vid) else snap["last_contact_h"]
        status = classify(coverage, v["p_comms_loss"], last_h)
        reason = []
        if v["p_comms_loss"] >= 0.5:
            reason.append(f"telecom {v['comms']} disruption risk {v['p_comms_loss']:.0%}")
        if last_h >= 4:
            reason.append(f"last confirmed field contact {last_h:g} h ago")
        if coverage < 0.15:
            reason.append(f"only {observed:,} of ~{predicted:,} predicted-affected residents observed")
        rows.append({
            "village_id": vid, "name": v["name"], "lat": v["lat"], "lon": v["lon"], "pop": v["pop"],
            "predicted_affected": predicted, "verified_contacts": snap["verified_contacts"],
            "shelter_checkins": snap["shelter_checkins"], "reports": reports, "live_reports": live.get(vid, 0),
            "observed": observed, "coverage": round(coverage, 3), "comms_loss_risk": v["p_comms_loss"],
            "comms_tower": v["comms"], "last_contact_h": last_h, "status": status,
            "reason": "; ".join(reason),
            "recommendation": "Dispatch field verification team" if status == "POSSIBLE BLIND SPOT"
            else ("Request contact confirmation" if status == "UNVERIFIED" else
                  ("Continue monitoring" if status == "PARTIALLY OBSERVED" else "No action")),
        })
    order = {"POSSIBLE BLIND SPOT": 0, "UNVERIFIED": 1, "PARTIALLY OBSERVED": 2, "REACHED": 3}
    rows.sort(key=lambda r: (order[r["status"]], r["coverage"]))
    return {
        "reach_version": REACH_VERSION,
        "data_label": "SYNTHETIC field snapshot (T+6h) + live reports submitted in this session",
        "caveat": "A possible coverage gap requires verification. Missing reports do not prove harm, and reports do not prove absence of harm.",
        "summary": {s: sum(1 for r in rows if r["status"] == s) for s in order},
        "villages": rows,
    }
