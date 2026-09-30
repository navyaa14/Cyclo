"""
IBTrACS adapter (production path for real cyclone tracks).

Download the North Indian basin CSV from NOAA NCEI:
  https://www.ncei.noaa.gov/products/international-best-track-archive  (file: ibtracs.NI.list.v04r01.csv)
Then:
  from app.adapters.ibtracs import load_track
  track = load_track("ibtracs.NI.list.v04r01.csv", name="FANI", season=2019, landfall_iso="2019-05-03 03:00:00")
and replace demo_scenario.TRACK with the result (hours relative to landfall, lat, lon, vmax km/h).

Wind: prefers WMO_WIND, then USA_WIND (knots, converted to km/h). Note: agencies use different
averaging periods (IMD 3-min vs JTWC 1-min), so document which column you used.
"""
from __future__ import annotations

import csv
from datetime import datetime

KT_TO_KMH = 1.852


def load_track(path: str, name: str, season: int, landfall_iso: str):
    t0 = datetime.fromisoformat(landfall_iso)
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = csv.DictReader(fh)
        for r in rows:
            if r.get("NAME", "").strip().upper() != name.upper():
                continue
            if str(r.get("SEASON", "")).strip() != str(season):
                continue
            try:
                t = datetime.fromisoformat(r["ISO_TIME"].strip())
                lat, lon = float(r["LAT"]), float(r["LON"])
            except (ValueError, KeyError):
                continue  # IBTrACS has a units row directly under the header
            wind = None
            for col in ("WMO_WIND", "USA_WIND"):
                v = (r.get(col) or "").strip()
                if v:
                    try:
                        wind = float(v) * KT_TO_KMH
                        break
                    except ValueError:
                        pass
            if wind is None:
                continue
            out.append(((t - t0).total_seconds() / 3600.0, lat, lon, round(wind)))
    return sorted(out)
