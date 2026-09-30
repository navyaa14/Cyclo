"""
Response optimizer: greedy marginal-gain selection under resource constraints.

Objective (lower is better):
    J = expected degraded-access population
      + 4000 x sum(PHC disruption probability)
      + 1000 x sum(telecom disruption probability)
      + 60 x number of interventions               (prefer fewer actions)

Greedy is NOT guaranteed globally optimal; the UI and README say so.
"""
from __future__ import annotations

from ..data import demo_scenario as D
from . import cascade as C

OPTIMIZER_VERSION = "greedy-marginal-0.2"
RESOURCE_OF = {"generator": "generators", "ambulance": "ambulances", "rescue_team": "rescue_teams",
               "portable_telecom": "telecom_units"}
PHC_IDS = [a["id"] for a in D.ASSETS if a["type"] == "phc"]
TEL_IDS = [a["id"] for a in D.ASSETS if a["type"] == "telecom"]


def objective(res, n_actions):
    p = res["p"]
    return (res["metrics"]["expected_degraded_pop"] + 4000 * sum(p[x] for x in PHC_IDS)
            + 1000 * sum(p[x] for x in TEL_IDS) + 60 * n_actions)


def label(it):
    t = it["type"]
    if t == "generator":
        return f"Deploy backup generator to {it['target']}"
    if t == "relocate_generator":
        return f"Move generator {it['source']} to {it['target']}"
    if t == "portable_telecom":
        return f"Deploy portable telecom unit at {it['target']}"
    if t == "ambulance":
        return f"Pre-position ambulance: {C.STAGING_INDEX[it['target']]['name']}"
    if t == "rescue_team":
        return f"Assign rescue team to assisted evacuation of {C.VILLAGE_INDEX[it['target']]['name']}"
    if t == "activate_shelter":
        return f"Activate secondary shelter {it['target']}"
    if t == "reroute":
        v = C.VILLAGE_INDEX[it["village"]]
        opt = v["alts"][int(it.get("option", 0))]
        via = " + ".join(opt["route"]) if opt["route"] else "local road"
        cur = v["shelter"]
        cur_via = " + ".join(cur["route"]) if cur["route"] else "local road"
        pre = f"Activate {opt['shelter']} and reroute" if it.get("activate") else "Reroute"
        return f"{pre} {v['name']} evacuation to {opt['shelter']} via {via} (instead of {cur['shelter']} via {cur_via})"
    return t


def candidates(state=None):
    state = state or C.base_state()
    out = []
    for a in D.ASSETS:
        if a["type"] in ("phc", "pump", "telecom") and a["id"] not in state.generators_at:
            out.append({"type": "generator", "target": a["id"]})
    for src in state.generators_at:
        for a in D.ASSETS:
            if a["type"] == "phc" and a["id"] not in state.generators_at:
                out.append({"type": "relocate_generator", "source": src, "target": a["id"]})
    for a in D.ASSETS:
        if a["type"] == "telecom":
            out.append({"type": "portable_telecom", "target": a["id"]})
    for sp in D.STAGING_POINTS:
        out.append({"type": "ambulance", "target": sp["id"]})
    for a in D.ASSETS:
        if a["type"] == "shelter" and a.get("inactive"):
            out.append({"type": "activate_shelter", "target": a["id"]})
    for v in D.VILLAGES:
        for i, alt in enumerate(v["alts"]):
            cand = {"type": "reroute", "village": v["id"], "option": i}
            if not state.shelter_active.get(alt["shelter"], True):
                cand["activate"] = True
            out.append(cand)
        out.append({"type": "rescue_team", "target": v["id"]})
    for c in out:
        c["label"] = label(c)
        c["resource"] = RESOURCE_OF.get(c["type"])
    return out


def _key(it):
    return (it["type"], it.get("target"), it.get("village"), it.get("source"), it.get("option"), it.get("activate"))


def _conflicts(chosen, cand):
    for c in chosen:
        if _key(c) == _key(cand):
            return True
        if cand["type"] == "reroute" and c["type"] == "reroute" and c["village"] == cand["village"]:
            return True
        if cand["type"] == "rescue_team" and c["type"] == "rescue_team" and c["target"] == cand["target"]:
            return True
        if cand["type"] == "relocate_generator" and c["type"] == "relocate_generator" and c["source"] == cand["source"]:
            return True
        if cand["type"] in ("generator", "relocate_generator") and c["type"] in ("generator", "relocate_generator") \
                and c["target"] == cand["target"]:
            return True
    return False


def explain(before, after, it):
    bv, av = before["villages"], after["villages"]
    gains = sorted(((bv[k]["expected_degraded_pop"] - av[k]["expected_degraded_pop"], k) for k in bv), reverse=True)
    top = [f"{bv[k]['name']}" for g, k in gains if g >= 50][:4]
    people = before["metrics"]["expected_degraded_pop"] - after["metrics"]["expected_degraded_pop"]
    parts = []
    if people > 0:
        parts.append(f"Cuts expected degraded-access population by {people:,}" + (f" ({', '.join(top)})" if top else ""))
    for x in PHC_IDS + TEL_IDS:
        b, a = before["p"][x], after["p"][x]
        if b - a >= 0.1:
            parts.append(f"{x} disruption probability {b:.0%} to {a:.0%}")
    tgt = it.get("target")
    if it["type"] in ("generator", "relocate_generator") and tgt:
        k = C._power_edge_into(before["state"], tgt)
        if k:
            parts.append(f"{tgt} depends on {k[0]} (disruption risk {before['p'][k[0]]:.0%})")
    return "; ".join(parts) + "." if parts else "Marginal benefit below reporting threshold."


def optimize(scenario="expected", resources=None, base_interventions=None, overrides=None, forced=None,
             max_steps=12, min_gain=80.0):
    resources = dict(resources or D.DEFAULT_RESOURCES)
    chosen = list(base_interventions or [])
    remaining = dict(resources)
    for c in chosen:
        r = RESOURCE_OF.get(c["type"])
        if r:
            remaining[r] = remaining.get(r, 0) - 1
    baseline = C.evaluate(scenario, chosen, overrides, forced)
    current = baseline
    steps = []
    for _ in range(max_steps):
        best = None
        cur_obj = objective(current, len(chosen))
        for cand in candidates(current["state"]):
            r = cand["resource"]
            if r and remaining.get(r, 0) <= 0:
                continue
            if _conflicts(chosen, cand):
                continue
            it = {k: v for k, v in cand.items() if k not in ("label", "resource")}
            try:
                res = C.evaluate(scenario, chosen + [it], overrides, forced)
            except ValueError:
                continue
            gain = cur_obj - objective(res, len(chosen) + 1)
            if best is None or gain > best[0]:
                best = (gain, it, res, cand)
        if not best or best[0] < min_gain:
            break
        gain, it, res, cand = best
        steps.append({
            "rank": len(steps) + 1, "intervention": it, "label": cand["label"], "resource": cand["resource"],
            "people_protected": current["metrics"]["expected_degraded_pop"] - res["metrics"]["expected_degraded_pop"],
            "objective_gain": round(gain, 1), "why": explain(current, res, it),
        })
        chosen.append(it)
        if cand["resource"]:
            remaining[cand["resource"]] -= 1
        current = res
    return {
        "algorithm": "Greedy marginal-gain selection (not guaranteed globally optimal)",
        "optimizer_version": OPTIMIZER_VERSION,
        "resources": resources, "resources_remaining": remaining,
        "plan": steps, "interventions": chosen,
        "before": baseline["metrics"], "after": current["metrics"],
    }
