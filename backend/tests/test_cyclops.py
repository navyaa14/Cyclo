import json
import os

import networkx as nx
import numpy as np
import pytest

os.environ["CYCLOPS_DISABLE_GEMINI"] = "1"  # tests are deterministic and offline

from fastapi.testclient import TestClient  # noqa: E402

from app.data import demo_scenario as D  # noqa: E402
from app.engines import assets as A, cascade as C, hazard as H, optimizer as O, reach as RG, verify as V  # noqa: E402
from app.main import app  # noqa: E402
from app.services import reports as R, gemini as G  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    R.reset()
    V.reset()
    yield


# ---------------- hazard ----------------
def test_hazard_scores_bounded():
    for s in D.SCENARIOS:
        for c in H.grid(s):
            for k in ("wind_risk", "rain_risk", "inundation_risk", "combined_hazard", "confidence"):
                assert 0.0 <= c[k] <= 1.0, (s, k, c[k])


def test_severe_scenario_not_less_hazardous_than_low():
    low = np.mean([c["combined_hazard"] for c in H.grid("conservative")])
    high = np.mean([c["combined_hazard"] for c in H.grid("severe")])
    assert high > low


def test_scenario_reproducible():
    H.grid.cache_clear()
    a = H.grid("expected")
    H.grid.cache_clear()
    b = H.grid("expected")
    assert a == b


# ---------------- assets ----------------
def test_fragility_monotonic():
    assert A.fragility_risk(0.6, 0.5) > A.fragility_risk(0.3, 0.5)
    assert A.fragility_risk(0.4, 0.8) > A.fragility_risk(0.4, 0.2)
    assert 0 <= A.fragility_risk(5, 1) <= 1 and 0 <= A.fragility_risk(-5, 0) <= 1


def test_contributions_sum_to_one():
    for aid, r in A.asset_risks("expected").items():
        assert abs(sum(c["share"] for c in r["contributions"]) - 1.0) < 0.01, aid
        assert r["risk_low"] <= r["direct_risk"] <= r["risk_high"]


# ---------------- cascade ----------------
def test_substation_failure_propagates_to_phc():
    base = C.evaluate("expected")
    forced = C.evaluate("expected", forced={"P04": 1.0})
    assert forced["p"]["PHC-7"] > base["p"]["PHC-7"]
    assert forced["p"]["T07"] >= base["p"]["T07"]
    assert forced["metrics"]["expected_degraded_pop"] >= base["metrics"]["expected_degraded_pop"]


def test_cycle_handling_converges():
    s = C.base_state()
    G_ = C.build_graph(s)
    G_.add_edge("PHC-7", "P04", dependency_type="test", strength=0.5, backup=0.0, restoration_time_h=1, confidence=0.5)
    assert not nx.is_directed_acyclic_graph(G_)
    direct = {k: v["direct_risk"] for k, v in A.asset_risks("expected").items()}
    p, iters = C.propagate(G_, direct, {})
    assert iters < 200
    assert all(0 <= x <= 1 for x in p.values())


def test_generator_reduces_phc_risk():
    base = C.evaluate("expected")
    gen = C.evaluate("expected", [{"type": "generator", "target": "PHC-7"}])
    assert gen["p"]["PHC-7"] < base["p"]["PHC-7"]


def test_intervention_rollback_equals_baseline():
    base = C.evaluate("expected")
    applied = C.evaluate("expected", [{"type": "reroute", "village": "V14", "option": 0}])
    rolled = C.evaluate("expected", [])
    assert applied["metrics"] != base["metrics"]
    assert rolled["metrics"] == base["metrics"]


def test_invalid_intervention_rejected():
    with pytest.raises(ValueError):
        C.evaluate("expected", [{"type": "teleport", "target": "PHC-7"}])
    r = client.post("/api/simulate", json={"scenario": "expected", "interventions": [{"type": "teleport"}]})
    assert r.status_code == 400


# ---------------- optimizer ----------------
def test_optimizer_respects_resources():
    res = {"generators": 1, "ambulances": 0, "rescue_teams": 1, "telecom_units": 0}
    out = O.optimize("expected", res)
    used = {}
    for step in out["plan"]:
        if step["resource"]:
            used[step["resource"]] = used.get(step["resource"], 0) + 1
    for k, v in used.items():
        assert v <= res[k], (k, v)
    assert all(v >= 0 for v in out["resources_remaining"].values())


def test_optimizer_improves_objective():
    out = O.optimize("expected")
    assert out["after"]["expected_degraded_pop"] < out["before"]["expected_degraded_pop"]
    assert out["after"]["resilience_score"] > out["before"]["resilience_score"]


# ---------------- reach gap ----------------
def test_reach_gap_classification_rules():
    assert RG.classify(0.6, 0.9, 10) == "REACHED"
    assert RG.classify(0.2, 0.9, 10) == "PARTIALLY OBSERVED"
    assert RG.classify(0.05, 0.7, 1) == "POSSIBLE BLIND SPOT"
    assert RG.classify(0.05, 0.1, 5) == "POSSIBLE BLIND SPOT"
    assert RG.classify(0.05, 0.1, 1) == "UNVERIFIED"


def test_village_k_flagged():
    out = RG.reach_gap(C.evaluate("expected"))
    vk = next(r for r in out["villages"] if r["village_id"] == "VK")
    assert vk["status"] == "POSSIBLE BLIND SPOT"


# ---------------- reports ----------------
def test_duplicate_report_is_idempotent():
    data = {"text": "Electric pole fallen on road", "lat": 19.865, "lon": 85.935, "client_report_id": "dup-1"}
    a = client.post("/api/reports", data=data).json()
    b = client.post("/api/reports", data=data).json()
    assert a["id"] == b["id"] and b.get("idempotent_replay")
    assert len(R.list_reports()) == 1


def test_near_duplicates_clustered():
    client.post("/api/reports", data={"text": "Electric pole fallen", "lat": 19.865, "lon": 85.935, "client_report_id": "c1"})
    b = client.post("/api/reports", data={"text": "power pole down wires", "lat": 19.866, "lon": 85.936, "client_report_id": "c2"}).json()
    assert b["duplicate_of"] is not None


def test_invalid_gemini_json_goes_to_review():
    meta = {}
    ex, meta = R.validate_extraction('{"incident_type": "ALIENS", "confidence": 7}', meta)
    assert ex is None and meta["validation"] == "failed"
    ex, meta = R.validate_extraction("not json at all", {})
    assert ex is None


def test_approved_report_updates_graph():
    base = client.post("/api/simulate", json={"scenario": "expected"}).json()
    p04 = next(n for n in base["nodes"] if n["id"] == "P04")["p"]
    rep = client.post("/api/reports", data={"text": "Electric pole collapsed, wires fallen", "lat": 19.865,
                                            "lon": 85.935, "client_report_id": "g1"}).json()
    client.post(f"/api/reports/{rep['id']}/review", json={"decision": "approve"})
    after = client.post("/api/simulate", json={"scenario": "expected"}).json()
    assert next(n for n in after["nodes"] if n["id"] == "P04")["p"] >= p04


def test_offline_sync_replay_uses_captured_time():
    t = 1_700_000_000.0
    r = client.post("/api/reports", data={"text": "road blocked by tree", "lat": 19.9, "lon": 86.0,
                                          "client_report_id": "off-1", "captured_at": t}).json()
    assert r["captured_at"] == t
    again = client.post("/api/reports", data={"text": "road blocked by tree", "lat": 19.9, "lon": 86.0,
                                              "client_report_id": "off-1", "captured_at": t}).json()
    assert again["id"] == r["id"]


def test_report_outside_district_rejected():
    r = client.post("/api/reports", data={"text": "x", "lat": 28.6, "lon": 77.2})
    assert r.status_code == 400


# ---------------- grounding ----------------
def test_numbers_grounding_guard():
    facts = json.dumps({"shelter": "S5", "route": "R9", "emergency_number": "112"})
    assert G.numbers_grounded("Go to S5 via R9. Call 112.", facts)[0]
    ok, extra = G.numbers_grounded("Winds of 240 km/h expected. Go to S5.", facts)
    assert not ok and "240" in extra


# ---------------- verify ----------------
def test_verify_metrics_bounded_and_errors_reported():
    v = V.verify("expected")
    assert 0 <= v["flood"]["iou"] <= 1
    assert any(m["asset_id"] == "R21" and m["error_type"] == "FALSE_POSITIVE" for m in v["failure_memory"])


# ---------------- end to end ----------------
def test_end_to_end_flow():
    assert client.get("/api/cyclones").status_code == 200
    assert client.get("/api/hazard").status_code == 200
    base = client.post("/api/simulate", json={"scenario": "expected", "forced": {"P04": 1.0}}).json()
    assert base["cascade"]["direct_impact_count"] > 0
    plan = client.post("/api/optimize", json={"scenario": "expected"}).json()
    assert plan["plan"]
    after = client.post("/api/simulate", json={"scenario": "expected", "interventions": plan["interventions"]}).json()
    before = client.post("/api/simulate", json={"scenario": "expected"}).json()
    assert after["metrics"]["expected_degraded_pop"] < before["metrics"]["expected_degraded_pop"]
    brief = client.post("/api/brief", json={"scenario": "expected", "interventions": plan["interventions"]}).json()
    assert "Incident brief" in brief["markdown"]
    st = client.post("/api/stress-test").json()
    assert st["system_still_produced_plan"]


def test_alerts_never_route_over_avoided_assets():
    for scen in D.SCENARIOS:
        sim = C.evaluate(scen)
        from app.services import comms
        for vid in sim["villages"]:
            f = comms.alert_facts(sim, vid, scen)
            assert not set(f["avoid"]) & set(f["route"].split(" + ")), (scen, vid, f)
            msgs = comms.template_alerts(f)
            ok, extra = G.numbers_grounded(" ".join(msgs.values()), json.dumps(f, ensure_ascii=False))
            assert ok, (vid, extra)
