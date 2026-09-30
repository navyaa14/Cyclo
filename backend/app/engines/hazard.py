"""
Hazard engine: explainable geospatial proxy model.

This is NOT a hydrodynamic storm-surge model (e.g. ADCIRC). It is a transparent proxy:
  wind       - modified Rankine vortex along the hourly-interpolated track, right-of-motion boost
  rain       - accumulated rain proxy decaying with distance from the storm centre
  inundation - coastal surge proxy (peak right of landfall, exponential inland decay, enhanced
               along channels) minus ground elevation, combined with pluvial ponding in low areas
All outputs are normalised to [0, 1].
"""
from __future__ import annotations

from functools import lru_cache
import numpy as np

from ..data import demo_scenario as D

HAZARD_MODEL_VERSION = "hazard-proxy-0.3"
LAT0, LON0 = 19.9, 85.9
KX = 111.32 * np.cos(np.radians(LAT0))
KY = 111.0
WEIGHTS = {"wind": 0.40, "rain": 0.25, "inundation": 0.35}


def to_xy(lat, lon):
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    return (lon - LON0) * KX, (lat - LAT0) * KY


def _polyline_xy(poly):
    return [to_xy(a, b) for a, b in poly]


def _dist_to_polyline(x, y, pts):
    """Distance (km) to a polyline, signed side of the nearest segment, and along-line position."""
    best = np.full(np.shape(x), np.inf)
    side = np.zeros(np.shape(x))
    along = np.zeros(np.shape(x))
    cum = 0.0
    for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:]):
        dx, dy = bx - ax, by - ay
        seg = float(np.hypot(dx, dy))
        t = np.clip(((x - ax) * dx + (y - ay) * dy) / (seg ** 2), 0, 1)
        px, py = ax + t * dx, ay + t * dy
        d = np.hypot(x - px, y - py)
        cross = dx * (y - ay) - dy * (x - ax)
        closer = d < best
        best = np.where(closer, d, best)
        side = np.where(closer, np.sign(cross), side)
        along = np.where(closer, cum + t * seg, along)
        cum += seg
    return best, side, along


COAST_XY = _polyline_xy(D.COAST)
CHANNELS_XY = [_polyline_xy(c) for c in D.CHANNELS]


def coast_distance_km(lat, lon):
    x, y = to_xy(lat, lon)
    d, side, along = _dist_to_polyline(x, y, COAST_XY)
    return d, side > 0, along


def channel_factor(lat, lon):
    x, y = to_xy(lat, lon)
    f = np.zeros(np.shape(x))
    for ch in CHANNELS_XY:
        d, _, _ = _dist_to_polyline(x, y, ch)
        f = np.maximum(f, np.exp(-(d / 1.2) ** 2))
    return f


def elevation_m(lat, lon):
    """SYNTHETIC DEM. Replace with SRTM / Copernicus DEM sampling in production."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    d, _, _ = coast_distance_km(lat, lon)
    base = 1.2 + 0.55 * d + 0.8 * np.sin(lat * 37.0) * np.cos(lon * 29.0)
    base = base - 2.2 * channel_factor(lat, lon)
    return np.clip(base, 0.3, None)


def _track_hourly(scen):
    hrs = np.array([p[0] for p in D.TRACK], dtype=float)
    lats = np.array([p[1] for p in D.TRACK])
    lons = np.array([p[2] for p in D.TRACK])
    vmax = np.array([p[3] for p in D.TRACK], dtype=float)
    h = np.arange(hrs.min(), hrs.max() + 1, 1.0)
    la = np.interp(h, hrs, lats)
    lo = np.interp(h, hrs, lons)
    v = np.interp(h, hrs, vmax) * scen["vmax_scale"]
    x, y = to_xy(la, lo)
    x = x + scen["track_shift_km"]  # shift east (+) / west (-)
    heading = np.arctan2(np.gradient(y), np.gradient(x))
    return h, x, y, v, heading


def track_geojson(scenario: str = "expected"):
    scen = D.SCENARIOS[scenario]
    h, x, y, v, _ = _track_hourly(scen)
    lat = y / KY + LAT0
    lon = x / KX + LON0
    return [{"hour": float(a), "lat": round(float(b), 4), "lon": round(float(c), 4), "vmax_kmh": round(float(d))}
            for a, b, c, d in zip(h, lat, lon, v)]


def hazard_components(lat, lon, scenario: str = "expected", plinth_m=0.0):
    """Vectorised hazard at points. Returns dict of arrays in [0,1] plus raw physical proxies."""
    scen = D.SCENARIOS[scenario]
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    plinth = np.broadcast_to(np.asarray(plinth_m, dtype=float), lat.shape)
    x, y = to_xy(lat, lon)
    h, tx, ty, tv, heading = _track_hourly(scen)
    rmax = 25.0 * scen["rmax_scale"]

    vcell = np.zeros(lat.shape)
    rain = np.zeros(lat.shape)
    for i in range(len(h)):
        dx, dy = x - tx[i], y - ty[i]
        r = np.maximum(np.hypot(dx, dy), 0.5)
        vv = np.where(r < rmax, tv[i] * r / rmax, tv[i] * (rmax / r) ** 0.55)
        ang = np.arctan2(dy, dx)
        right = heading[i] - np.pi / 2
        vv = vv * (1 + 0.10 * np.cos(ang - right))
        vcell = np.maximum(vcell, vv)
        rain += 11.0 * (tv[i] / 185.0) * np.exp(-r / 90.0) * scen["rain_scale"]

    wind_risk = np.clip((vcell - 62.0) / (260.0 - 62.0), 0, 1)
    rain_risk = np.clip(rain / 320.0, 0, 1)

    d, _, along = coast_distance_km(lat, lon)
    lfx, lfy = to_xy(*D.LANDFALL)
    _, _, s0 = _dist_to_polyline(np.array([lfx + scen["track_shift_km"]]), np.array([lfy]), COAST_XY)
    v_land = float(np.interp(0, [p[0] for p in D.TRACK], [p[3] for p in D.TRACK])) * scen["vmax_scale"]
    surge_coast = 1.9 * scen["surge_scale"] * (v_land / 185.0) ** 2 * np.exp(-((along - s0[0] - 12.0) / 35.0) ** 2)
    chf = channel_factor(lat, lon)
    d_eff = d * (1 - 0.6 * chf)
    level = surge_coast * np.exp(-d_eff / 3.5)
    elev = elevation_m(lat, lon) + plinth
    depth = np.maximum(0.0, level - np.maximum(0.0, elev - 1.2))
    a = 1 - np.exp(-depth / 0.4)
    pluvial = rain_risk * np.clip((5.0 - elev) / 4.0, 0, 1)
    inund = 1 - (1 - a) * (1 - 0.55 * pluvial)

    combined = WEIGHTS["wind"] * wind_risk + WEIGHTS["rain"] * rain_risk + WEIGHTS["inundation"] * inund
    return {
        "wind": wind_risk, "rain": rain_risk, "inundation": inund, "combined": combined,
        "wind_kmh": vcell, "rain_mm": rain, "surge_depth_m": depth, "elevation_m": elev,
        "coast_km": d,
    }


@lru_cache(maxsize=8)
def grid(scenario: str = "expected"):
    g = D.GRID
    lats = np.arange(g["lat_min"], g["lat_max"] + 1e-9, g["step"])
    lons = np.arange(g["lon_min"], g["lon_max"] + 1e-9, g["step"])
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    la, lo = LA.ravel(), LO.ravel()
    _, land, _ = coast_distance_km(la, lo)
    la, lo = la[land], lo[land]
    hz = hazard_components(la, lo, scenario)
    lowc = hazard_components(la, lo, "conservative")["combined"]
    highc = hazard_components(la, lo, "severe")["combined"]
    conf = np.clip(1 - 1.5 * (highc - lowc), 0.3, 0.95)
    cells = []
    for i in range(len(la)):
        cells.append({
            "cell_id": f"C{i:04d}", "lat": round(float(la[i]), 4), "lon": round(float(lo[i]), 4),
            "wind_risk": round(float(hz["wind"][i]), 3), "rain_risk": round(float(hz["rain"][i]), 3),
            "inundation_risk": round(float(hz["inundation"][i]), 3),
            "combined_hazard": round(float(hz["combined"][i]), 3),
            "combined_low": round(float(lowc[i]), 3), "combined_high": round(float(highc[i]), 3),
            "confidence": round(float(conf[i]), 2),
        })
    return tuple(cells)
