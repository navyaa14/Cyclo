"""
Infrastructure dependency graph + probabilistic cascade simulator + intervention model.

Node disruption probability (independence assumption, documented as a limitation):
    p_n = 1 - (1 - d_n) * PROD_parents (1 - p_u * strength_un * (1 - backup_un))
Solved by fixed-point iteration, so dependency cycles are handled (converges because each
update is monotone and bounded).

Village service losses:
    health  = 1 - (1 - p_phc) * PROD_route (1 - p_asset)          [x ambulance multiplier]
    shelter = 1 - (1 - p_shelter) * PROD_route (1 - p_asset) * (1 - overflow)   [x rescue multiplier]
    degraded access = 1 - (1 - health) * (1 - shelter)
Population figures are EXPECTED values (sum of population x probability).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import networkx as nx

from ..data import demo_scenario as D
from . import assets as A

CASCADE_MODEL_VERSION = "cascade-fixedpoint-0.3"
VILLAGE_INDEX = {v["id"]: v for v in D.VILLAGES}
STAGING_INDEX = {s["id"]: s for s in D.STAGING_POINTS}
CRITICAL_TYPES = {"substation", "telecom", "phc", "bridge", "road", "shelter", "pump"}

MULT_AMBULANCE = 0.55
MULT_RESCUE = 0.60
MULT_PORTABLE_TELECOM = 0.30
GENERATOR_BACKUP = 0.85


@dataclass
class State:
    edges: dict = field(default_factory=dict)          # (u,v) -> attrs
    villages: dict = field(default_factory=dict)       # id -> village def (mutable copy)
    shelter_active: dict = field(default_factory=dict)
    node_mult: dict = field(default_factory=dict)      # asset -> multiplier on final p
    health_mult: dict = field(default_factory=dict)    # village -> multiplier
    shelter_mult: dict = field(default_factory=dict)   # village -> multiplier
    generators_at: set = field(default_factory=set)
    notes: list = field(default_factory=list)


def base_state() -> State:
    s = State()
    for u, v, t, st, b, rh, c in D.EDGES:
        s.edges[(u, v)] = {"dependency_type": t, "strength": st, "backup": b, "restoration_time_h": rh, "confidence": c}
    s.villages = {v["id"]: copy.deepcopy(v) for v in D.VILLAGES}
    s.shelter_active = {a["id"]: not a.get("inactive", False) for a in D.ASSETS if a["type"] == "shelter"}
    s.generators_at = set(D.EXISTING_GENERATORS)
    return s


def _power_edge_into(state, target):
    for (u, v), e in state.edges.items():
        if v == target and e["dependency_type"] == "power":
            return (u, v)
    return None


def apply_interventions(state: State, interventions: list) -> State:
    """Apply a list of intervention dicts. Unknown/invalid ones raise ValueError."""
    s = copy.deepcopy(state)
    for it in interventions:
        t = it.get("type")
        if t == "generator":
            k = _power_edge_into(s, it["target"])
            if not k:
                raise ValueError(f"No power dependency into {it['target']}")
            s.edges[k]["backup"] = max(s.edges[k]["backup"], GENERATOR_BACKUP)
            s.generators_at.add(it["target"])
        elif t == "relocate_generator":
            src, dst = it["source"], it["target"]
            if src not in s.generators_at:
                raise ValueError(f"No generator at {src}")
            ks, kd = _power_edge_into(s, src), _power_edge_into(s, dst)
            if not ks or not kd:
                raise ValueError("Relocation endpoints need a power dependency")
            s.edges[ks]["backup"] = 0.0
            s.edges[kd]["backup"] = max(s.edges[kd]["backup"], GENERATOR_BACKUP)
            s.generators_at.discard(src)
            s.generators_at.add(dst)
        elif t == "portable_telecom":
            s.node_mult[it["target"]] = s.node_mult.get(it["target"], 1.0) * MULT_PORTABLE_TELECOM
        elif t == "ambulance":
            sp = STAGING_INDEX[it["target"]]
            for vid in sp["villages"]:
                s.health_mult[vid] = s.health_mult.get(vid, 1.0) * MULT_AMBULANCE
        elif t == "rescue_team":
            s.shelter_mult[it["target"]] = s.shelter_mult.get(it["target"], 1.0) * MULT_RESCUE
        elif t == "activate_shelter":
            s.shelter_active[it["target"]] = True
        elif t == "reroute":
            v = s.villages[it["village"]]
            opt = v["alts"][int(it.get("option", 0))]
            v["shelter"] = copy.deepcopy(opt)
            if it.get("activate"):
                s.shelter_active[opt["shelter"]] = True
        else:
            raise ValueError(f"Unknown intervention type: {t}")
    return s


def build_graph(state: State) -> nx.DiGraph:
    G = nx.DiGraph()
    for a in D.ASSETS:
        G.add_node(a["id"], kind="asset", type=a["type"], name=a["name"])
    for (u, v), e in state.edges.items():
        G.add_edge(u, v, **e)
    for vid, v in state.villages.items():
        G.add_node(vid, kind="village", type="village", name=v["name"], pop=v["pop"])
        G.add_edge(v["power"], vid, dependency_type="power", strength=0.9, backup=0.0, restoration_time_h=12, confidence=0.8)
        G.add_edge(v["comms"], vid, dependency_type="comms", strength=0.9, backup=0.0, restoration_time_h=8, confidence=0.7)
        G.add_edge(v["health"]["phc"], vid, dependency_type="health", strength=1.0, backup=0.0, restoration_time_h=24, confidence=0.7)
        for r in v["health"]["route"]:
            G.add_edge(r, vid, dependency_type="health_route", strength=1.0, backup=0.0, restoration_time_h=24, confidence=0.7)
        G.add_edge(v["shelter"]["shelter"], vid, dependency_type="evacuation", strength=1.0, backup=0.0, restoration_time_h=0, confidence=0.7)
        for r in v["shelter"]["route"]:
            if G.has_edge(r, vid):
                G[r][vid]["dependency_type"] = "health+evac_route"
            else:
                G.add_edge(r, vid, dependency_type="evac_route", strength=1.0, backup=0.0, restoration_time_h=24, confidence=0.7)
    return G


def propagate(G: nx.DiGraph, direct: dict, node_mult: dict, max_iter: int = 200, tol: float = 1e-7):
    asset_nodes = [n for n, d in G.nodes(data=True) if d["kind"] == "asset"]
    p = {n: direct.get(n, 0.0) for n in asset_nodes}
    iters = 0
    for iters in range(1, max_iter + 1):
        delta = 0.0
        for n in asset_nodes:
            surv = 1.0 - direct.get(n, 0.0)
            for u in G.predecessors(n):
                if G.nodes[u]["kind"] != "asset":
                    continue
                e = G[u][n]
                surv *= 1.0 - p[u] * e["strength"] * (1.0 - e["backup"])
            new = (1.0 - surv) * node_mult.get(n, 1.0)
            delta = max(delta, abs(new - p[n]))
            p[n] = new
        if delta < tol:
            break
    return p, iters


def _prod_surv(ps):
    out = 1.0
    for x in ps:
        out *= (1.0 - x)
    return out


def evaluate(scenario: str = "expected", interventions: list | None = None,
             overrides: dict | None = None, forced: dict | None = None):
    """Run the full simulation. overrides/forced: asset -> minimum direct disruption probability."""
    interventions = interventions or []
    state = apply_interventions(base_state(), interventions)
    risks = A.asset_risks(scenario)
    direct = {k: v["direct_risk"] for k, v in risks.items()}
    for src in (overrides or {}), (forced or {}):
        for k, v in src.items():
            if k in direct:
                direct[k] = max(direct[k], float(v))
    for sid, active in state.shelter_active.items():
        if not active:
            direct[sid] = 1.0  # inactive shelter cannot receive evacuees
    G = build_graph(state)
    p, iters = propagate(G, direct, state.node_mult)

    # shelter load / overflow
    load = {}
    for v in state.villages.values():
        load[v["shelter"]["shelter"]] = load.get(v["shelter"]["shelter"], 0) + v["pop"] * D.EVACUATING_SHARE
    overflow = {}
    for sid, l in load.items():
        cap = A.ASSET_INDEX[sid].get("capacity", 1e9)
        overflow[sid] = max(0.0, 1 - cap / l) if l > 0 else 0.0

    villages = {}
    for vid, v in state.villages.items():
        health = 1 - (1 - p[v["health"]["phc"]]) * _prod_surv(p[r] for r in v["health"]["route"])
        health *= state.health_mult.get(vid, 1.0)
        sh = v["shelter"]["shelter"]
        shelter = 1 - (1 - p[sh]) * _prod_surv(p[r] for r in v["shelter"]["route"]) * (1 - overflow.get(sh, 0))
        shelter *= state.shelter_mult.get(vid, 1.0)
        degraded = 1 - (1 - health) * (1 - shelter)
        villages[vid] = {
            "id": vid, "name": v["name"], "lat": v["lat"], "lon": v["lon"], "pop": v["pop"],
            "p_power_loss": round(p[v["power"]], 3), "p_comms_loss": round(p[v["comms"]], 3),
            "p_health_loss": round(health, 3), "p_shelter_loss": round(shelter, 3),
            "p_degraded": round(degraded, 3),
            "expected_degraded_pop": round(v["pop"] * degraded),
            "shelter": sh, "shelter_route": v["shelter"]["route"], "phc": v["health"]["phc"],
            "health_route": v["health"]["route"], "power": v["power"], "comms": v["comms"],
        }

    metrics = compute_metrics(p, direct, villages)
    return {
        "p": p, "direct": direct, "villages": villages, "metrics": metrics, "graph": G,
        "state": state, "iterations": iters, "shelter_load": load, "shelter_overflow": overflow,
    }


def compute_metrics(p, direct, villages):
    crit = [a for a in D.ASSETS if a["type"] in CRITICAL_TYPES and not a.get("inactive")]
    phcs = [a["id"] for a in D.ASSETS if a["type"] == "phc"]
    total_pop = sum(v["pop"] for v in villages.values())
    degraded_pop = sum(v["pop"] * v["p_degraded"] for v in villages.values())
    shelter_pop = sum(v["pop"] * v["p_shelter_loss"] for v in villages.values())
    health_pop = sum(v["pop"] * v["p_health_loss"] for v in villages.values())
    critical_disrupted = sum(1 for a in crit if p[a["id"]] >= 0.5)
    phc_severe = sum(1 for x in phcs if p[x] >= 0.5)
    mean_phc = sum(p[x] for x in phcs) / len(phcs)
    mean_crit = sum(p[a["id"]] for a in crit) / len(crit)
    deg_frac = degraded_pop / total_pop
    resilience = 100 * (1 - (0.5 * deg_frac + 0.25 * mean_phc + 0.25 * mean_crit))
    direct_count = sum(1 for a in crit if direct[a["id"]] >= 0.5)
    return {
        "critical_assets_disrupted": critical_disrupted,
        "direct_assets_at_risk": direct_count,
        "phcs_severe_risk": phc_severe,
        "expected_degraded_pop": round(degraded_pop),
        "expected_without_shelter_route": round(shelter_pop),
        "expected_health_access_loss": round(health_pop),
        "total_pop": total_pop,
        "resilience_score": round(resilience, 1),
        "resilience_formula": "100 x (1 - (0.5 x degraded-pop share + 0.25 x mean PHC risk + 0.25 x mean critical-asset risk))",
    }


def cascade_levels(result, trigger_threshold=0.5, edge_threshold=0.15):
    """BFS from directly-at-risk assets along edges that carry meaningful risk. For animation."""
    G, p, direct = result["graph"], result["p"], result["direct"]
    vil = result["villages"]

    def node_p(n):
        return vil[n]["p_degraded"] if n in vil else p[n]

    seeds = [n for n in p if direct.get(n, 0) >= trigger_threshold and not A.ASSET_INDEX[n].get("inactive")]
    level = {n: 0 for n in seeds}
    frontier = list(seeds)
    edges_used = []
    while frontier:
        nxt = []
        for u in frontier:
            for v in G.successors(u):
                e = G[u][v]
                if v in vil and e["dependency_type"] == "power":
                    continue  # household power is not part of the degraded-access metric
                carried = node_p(u) * e["strength"] * (1 - e["backup"])
                if carried >= edge_threshold:
                    edges_used.append({"source": u, "target": v, "level": level[u] + 1, "carried": round(carried, 3)})
                    if v not in level:
                        level[v] = level[u] + 1
                        nxt.append(v)
        frontier = nxt
    levels = {}
    for n, l in level.items():
        levels.setdefault(l, []).append(n)
    downstream = [n for n in level if level[n] > 0]
    human = sum(vil[n]["expected_degraded_pop"] for n in downstream if n in vil)
    return {
        "seeds": seeds,
        "levels": [{"level": l, "nodes": sorted(ns)} for l, ns in sorted(levels.items())],
        "edges": edges_used,
        "direct_impact_count": len(seeds),
        "downstream_count": len([n for n in downstream if n not in vil]),
        "villages_reached": len([n for n in downstream if n in vil]),
        "human_impact_expected": human,
    }


def upstream_explanation(result, node):
    G, p = result["graph"], result["p"]
    vil = result["villages"]
    items = []
    for u in G.predecessors(node):
        e = G[u][node]
        pu = vil[u]["p_degraded"] if u in vil else p[u]
        items.append({"from": u, "dependency_type": e["dependency_type"], "upstream_risk": round(pu, 3),
                      "strength": e["strength"], "backup": e["backup"],
                      "carried_risk": round(pu * e["strength"] * (1 - e["backup"]), 3),
                      "confidence": e["confidence"]})
    return sorted(items, key=lambda x: -x["carried_risk"])


def downstream_population(result, node):
    G = result["graph"]
    vil = result["villages"]
    desc = nx.descendants(G, node)
    return sum(vil[n]["pop"] for n in desc if n in vil), sorted(n for n in desc if n in vil)
