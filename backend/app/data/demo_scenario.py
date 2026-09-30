"""
Deterministic demo scenario: coastal Puri district, Odisha.

PROVENANCE (read this before presenting any number):
- CYCLONE TRACK: an approximate replay track drawn to resemble Cyclone Fani (landfall near
  Puri, 3 May 2019). Positions and intensities are rounded demo values, NOT IBTrACS records.
  Use `app.adapters.ibtracs` to load the real IBTrACS track instead.
- COASTLINE: simplified 7-point polyline of the Puri-Konark coast.
- ELEVATION: synthetic DEM (rises inland, synthetic river channels). Replace with SRTM/Copernicus DEM.
- INFRASTRUCTURE, VILLAGES, POPULATIONS, DEPENDENCIES: SYNTHETIC. Asset codes (P04, B17, PHC-7...)
  are invented and placed approximately inside the region. They are not real facilities.
- FIELD / REACH DATA and POST-EVENT OBSERVATIONS: SYNTHETIC, seeded, reproducible.
"""

DATA_VERSION = "fani-replay-demo-v1"
EVENT = {
    "id": "FANI-2019-REPLAY",
    "name": "Cyclone Fani (replay)",
    "district": "Puri, Odisha (demo district)",
    "landfall_label": "03 May 2019, ~08:00 IST (replay)",
    "provenance": "Approximate replay track resembling Cyclone Fani. Rounded demo values, not IBTrACS records.",
}

# Coast polyline, ordered south-west -> north-east. Land is to the LEFT (north-west).
COAST = [
    (19.62, 85.45), (19.72, 85.66), (19.80, 85.83), (19.86, 86.00),
    (19.90, 86.12), (20.00, 86.30), (20.10, 86.45),
]

# Synthetic low-lying river channels (each ends at the coast).
CHANNELS = [
    [(20.05, 85.76), (19.99, 85.80), (19.90, 85.84), (19.815, 85.865)],   # passes under B11
    [(19.98, 85.93), (19.92, 85.965), (19.875, 85.99), (19.853, 85.995)],  # passes under B17
    [(20.00, 86.12), (19.94, 86.135), (19.905, 86.14)],                    # passes under B22
]

# Hours relative to landfall, lat, lon, vmax (km/h, rounded demo values).
TRACK = [
    (-24, 18.10, 85.10, 200), (-18, 18.60, 85.30, 200), (-12, 19.05, 85.48, 195),
    (-6, 19.45, 85.66, 190), (0, 19.82, 85.84, 185), (3, 20.05, 85.98, 150),
    (6, 20.30, 86.12, 120), (12, 20.90, 86.50, 85),
]
LANDFALL = (19.82, 85.84)

SCENARIOS = {
    "conservative": {"label": "Low", "vmax_scale": 0.88, "surge_scale": 0.80, "rain_scale": 0.85,
                     "rmax_scale": 0.9, "track_shift_km": 8.0},
    "expected": {"label": "Expected", "vmax_scale": 1.00, "surge_scale": 1.00, "rain_scale": 1.00,
                 "rmax_scale": 1.0, "track_shift_km": 0.0},
    "severe": {"label": "High", "vmax_scale": 1.08, "surge_scale": 1.30, "rain_scale": 1.20,
               "rmax_scale": 1.15, "track_shift_km": -6.0},
}

GRID = {"lat_min": 19.64, "lat_max": 20.34, "lon_min": 85.45, "lon_max": 86.45, "step": 0.025}

# Fragility weights (wind, flood, rain) per asset type. Documented in README.
FRAGILITY = {
    "substation": (0.45, 0.45, 0.10),
    "telecom":    (0.70, 0.20, 0.10),
    "phc":        (0.35, 0.45, 0.20),
    "bridge":     (0.05, 0.70, 0.25),
    "road":       (0.15, 0.60, 0.25),
    "shelter":    (0.30, 0.50, 0.20),
    "pump":       (0.20, 0.60, 0.20),
}

# vuln: 0 (robust) .. 1 (fragile). plinth_m: height above local ground for flood exposure.
ASSETS = [
    {"id": "GS1", "name": "Grid substation 132/33 kV", "type": "substation", "lat": 20.150, "lon": 85.800, "vuln": 0.15, "plinth_m": 1.0},
    {"id": "P01", "name": "Substation P01 (Puri town)", "type": "substation", "lat": 19.830, "lon": 85.800, "vuln": 0.40, "plinth_m": 0.5},
    {"id": "P02", "name": "Substation P02", "type": "substation", "lat": 19.970, "lon": 85.750, "vuln": 0.35, "plinth_m": 0.5},
    {"id": "P03", "name": "Substation P03 (Konark side)", "type": "substation", "lat": 19.950, "lon": 86.050, "vuln": 0.40, "plinth_m": 0.5},
    {"id": "P04", "name": "Substation P04 (coastal)", "type": "substation", "lat": 19.862, "lon": 85.930, "vuln": 0.62, "plinth_m": 0.0},
    {"id": "P05", "name": "Substation P05", "type": "substation", "lat": 20.080, "lon": 86.200, "vuln": 0.35, "plinth_m": 0.5},

    {"id": "T01", "name": "Telecom tower T01", "type": "telecom", "lat": 19.812, "lon": 85.820, "vuln": 0.30, "plinth_m": 0.0},
    {"id": "T02", "name": "Telecom tower T02", "type": "telecom", "lat": 19.930, "lon": 85.780, "vuln": 0.40, "plinth_m": 0.0},
    {"id": "T03", "name": "Telecom tower T03", "type": "telecom", "lat": 20.050, "lon": 85.880, "vuln": 0.35, "plinth_m": 0.0},
    {"id": "T06", "name": "Telecom tower T06", "type": "telecom", "lat": 20.100, "lon": 86.250, "vuln": 0.40, "plinth_m": 0.0},
    {"id": "T07", "name": "Telecom tower T07", "type": "telecom", "lat": 19.872, "lon": 85.950, "vuln": 0.35, "plinth_m": 0.0},
    {"id": "T08", "name": "Telecom tower T08", "type": "telecom", "lat": 19.902, "lon": 86.090, "vuln": 0.70, "plinth_m": 0.0},
    {"id": "T09", "name": "Telecom tower T09", "type": "telecom", "lat": 19.920, "lon": 86.020, "vuln": 0.45, "plinth_m": 0.0},

    {"id": "DH1", "name": "District HQ hospital", "type": "phc", "lat": 19.815, "lon": 85.835, "vuln": 0.20, "plinth_m": 1.5},
    {"id": "PHC-1", "name": "PHC-1", "type": "phc", "lat": 19.980, "lon": 85.720, "vuln": 0.35, "plinth_m": 0.8},
    {"id": "PHC-3", "name": "PHC-3", "type": "phc", "lat": 19.920, "lon": 85.870, "vuln": 0.35, "plinth_m": 0.8},
    {"id": "PHC-5", "name": "PHC-5", "type": "phc", "lat": 19.970, "lon": 86.030, "vuln": 0.40, "plinth_m": 0.6},
    {"id": "PHC-7", "name": "PHC-7", "type": "phc", "lat": 19.884, "lon": 85.970, "vuln": 0.45, "plinth_m": 0.4},
    {"id": "PHC-8", "name": "PHC-8", "type": "phc", "lat": 20.080, "lon": 86.180, "vuln": 0.35, "plinth_m": 0.8},

    {"id": "B11", "name": "Bridge B11", "type": "bridge", "lat": 19.990, "lon": 85.800, "vuln": 0.40, "plinth_m": 0.0},
    {"id": "B17", "name": "Bridge B17", "type": "bridge", "lat": 19.875, "lon": 85.990, "vuln": 0.55, "plinth_m": 1.4},
    {"id": "B22", "name": "Bridge B22", "type": "bridge", "lat": 19.925, "lon": 86.138, "vuln": 0.50, "plinth_m": 0.0},

    {"id": "R4", "name": "Coastal road R4", "type": "road", "lat": 19.845, "lon": 85.905, "vuln": 0.50, "plinth_m": 0.0},
    {"id": "R9", "name": "Inland road R9", "type": "road", "lat": 19.955, "lon": 85.930, "vuln": 0.25, "plinth_m": 0.5},
    {"id": "R12", "name": "Road R12", "type": "road", "lat": 19.835, "lon": 85.875, "vuln": 0.45, "plinth_m": 0.0},
    {"id": "R21", "name": "Coastal road R21 (elevated concrete)", "type": "road", "lat": 19.878, "lon": 86.040, "vuln": 0.50, "plinth_m": 0.0, "elevated": True},

    {"id": "S1", "name": "Cyclone shelter S1", "type": "shelter", "lat": 19.840, "lon": 85.840, "vuln": 0.10, "plinth_m": 2.0, "capacity": 8000},
    {"id": "S3", "name": "Cyclone shelter S3", "type": "shelter", "lat": 19.905, "lon": 86.020, "vuln": 0.10, "plinth_m": 2.0, "capacity": 6000},
    {"id": "S4", "name": "Cyclone shelter S4", "type": "shelter", "lat": 19.950, "lon": 85.850, "vuln": 0.10, "plinth_m": 2.0, "capacity": 7000},
    {"id": "S5", "name": "Cyclone shelter S5 (inland)", "type": "shelter", "lat": 19.975, "lon": 85.950, "vuln": 0.10, "plinth_m": 2.0, "capacity": 9000},
    {"id": "S6", "name": "Secondary shelter S6 (school)", "type": "shelter", "lat": 20.030, "lon": 86.120, "vuln": 0.20, "plinth_m": 1.0, "capacity": 5000, "inactive": True},

    {"id": "W1", "name": "Water pump W1", "type": "pump", "lat": 19.832, "lon": 85.860, "vuln": 0.40, "plinth_m": 0.3},
    {"id": "W2", "name": "Water pump W2", "type": "pump", "lat": 19.890, "lon": 85.960, "vuln": 0.45, "plinth_m": 0.2},
]

# Dependency edges: (upstream, downstream, dependency_type, strength, backup, restoration_h, confidence)
# downstream depends on upstream. backup = share of upstream-loss cases covered by a backup.
EDGES = [
    ("GS1", "P01", "power", 0.9, 0.0, 12, 0.85), ("GS1", "P02", "power", 0.9, 0.0, 12, 0.85),
    ("GS1", "P03", "power", 0.9, 0.0, 12, 0.85), ("GS1", "P04", "power", 0.9, 0.0, 12, 0.85),
    ("GS1", "P05", "power", 0.9, 0.0, 12, 0.85),
    ("P01", "T01", "power", 0.8, 0.3, 8, 0.75), ("P02", "T02", "power", 0.8, 0.3, 8, 0.75),
    ("P02", "T03", "power", 0.8, 0.3, 8, 0.75), ("P05", "T06", "power", 0.8, 0.3, 8, 0.75),
    ("P04", "T07", "power", 0.8, 0.3, 8, 0.75), ("P03", "T08", "power", 0.8, 0.3, 8, 0.75),
    ("P03", "T09", "power", 0.8, 0.3, 8, 0.75),
    ("P01", "DH1", "power", 0.85, 0.9, 6, 0.8), ("P02", "PHC-1", "power", 0.85, 0.0, 6, 0.8),
    ("P02", "PHC-3", "power", 0.85, 0.85, 6, 0.8), ("P03", "PHC-5", "power", 0.85, 0.0, 6, 0.8),
    ("P04", "PHC-7", "power", 0.85, 0.0, 6, 0.8), ("P05", "PHC-8", "power", 0.85, 0.0, 6, 0.8),
    ("P01", "W1", "power", 0.9, 0.0, 6, 0.8), ("P04", "W2", "power", 0.9, 0.0, 6, 0.8),
    ("W2", "PHC-7", "water", 0.35, 0.0, 12, 0.6), ("W1", "DH1", "water", 0.2, 0.5, 12, 0.6),
    ("T07", "PHC-7", "comms", 0.2, 0.0, 8, 0.6), ("T09", "PHC-5", "comms", 0.2, 0.0, 8, 0.6),
]

# Existing generator locations (for relocation actions).
EXISTING_GENERATORS = ["DH1", "PHC-3"]

# Villages (SYNTHETIC populations). routes list asset ids that must be passable.
VILLAGES = [
    {"id": "V01", "name": "V01", "lat": 19.830, "lon": 85.870, "pop": 6200, "power": "P01", "comms": "T01",
     "health": {"phc": "DH1", "route": ["R12"]}, "shelter": {"shelter": "S1", "route": []}, "alts": []},
    {"id": "V03", "name": "V03", "lat": 19.970, "lon": 85.700, "pop": 3100, "power": "P02", "comms": "T02",
     "health": {"phc": "PHC-1", "route": []}, "shelter": {"shelter": "S4", "route": ["B11"]}, "alts": []},
    {"id": "V05", "name": "V05", "lat": 19.995, "lon": 85.780, "pop": 2800, "power": "P02", "comms": "T02",
     "health": {"phc": "PHC-1", "route": ["B11"]}, "shelter": {"shelter": "S4", "route": []}, "alts": []},
    {"id": "V08", "name": "V08", "lat": 19.930, "lon": 85.820, "pop": 4100, "power": "P02", "comms": "T02",
     "health": {"phc": "PHC-3", "route": []}, "shelter": {"shelter": "S4", "route": []}, "alts": []},
    {"id": "V10", "name": "V10", "lat": 19.855, "lon": 85.925, "pop": 3500, "power": "P04", "comms": "T07",
     "health": {"phc": "PHC-7", "route": ["R4"]}, "shelter": {"shelter": "S5", "route": ["R9"]}, "alts": []},
    {"id": "V12", "name": "V12", "lat": 19.878, "lon": 85.962, "pop": 4300, "power": "P04", "comms": "T07",
     "health": {"phc": "PHC-7", "route": []}, "shelter": {"shelter": "S3", "route": ["B17", "R21"]},
     "alts": [{"shelter": "S5", "route": ["R9"]}]},
    {"id": "V14", "name": "V14", "lat": 19.866, "lon": 86.002, "pop": 5200, "power": "P04", "comms": "T07",
     "health": {"phc": "PHC-7", "route": ["B17"]}, "shelter": {"shelter": "S3", "route": ["B17", "R21"]},
     "alts": [{"shelter": "S5", "route": ["R9"]}]},
    {"id": "V16", "name": "V16", "lat": 19.905, "lon": 85.985, "pop": 2900, "power": "P03", "comms": "T09",
     "health": {"phc": "PHC-7", "route": ["B17"]}, "shelter": {"shelter": "S3", "route": ["R21"]},
     "alts": [{"shelter": "S5", "route": ["R9"]}]},
    {"id": "V18", "name": "V18", "lat": 19.925, "lon": 86.070, "pop": 3800, "power": "P03", "comms": "T09",
     "health": {"phc": "PHC-5", "route": []}, "shelter": {"shelter": "S3", "route": ["R21"]},
     "alts": [{"shelter": "S6", "route": ["B22"]}]},
    {"id": "VK", "name": "Village K", "lat": 19.890, "lon": 86.080, "pop": 2100, "power": "P03", "comms": "T08",
     "health": {"phc": "PHC-5", "route": ["B22"]}, "shelter": {"shelter": "S3", "route": ["R21", "B22"]},
     "alts": [{"shelter": "S6", "route": []}]},
    {"id": "V22", "name": "V22", "lat": 20.020, "lon": 86.160, "pop": 2600, "power": "P05", "comms": "T06",
     "health": {"phc": "PHC-8", "route": []}, "shelter": {"shelter": "S5", "route": ["R9"]},
     "alts": [{"shelter": "S6", "route": []}]},
    {"id": "V24", "name": "V24", "lat": 20.030, "lon": 86.300, "pop": 2400, "power": "P05", "comms": "T06",
     "health": {"phc": "PHC-8", "route": []}, "shelter": {"shelter": "S3", "route": ["B22", "R21"]},
     "alts": [{"shelter": "S6", "route": []}]},
    {"id": "V26", "name": "V26", "lat": 20.050, "lon": 85.950, "pop": 3000, "power": "P02", "comms": "T03",
     "health": {"phc": "PHC-1", "route": []}, "shelter": {"shelter": "S5", "route": []}, "alts": []},
]

EVACUATING_SHARE = 0.5  # share of village population expected to use public shelters

STAGING_POINTS = [
    {"id": "AMB-N-B17", "name": "North of Bridge B17", "lat": 19.895, "lon": 85.975, "villages": ["V12", "V14", "V16"]},
    {"id": "AMB-KONARK", "name": "Konark junction", "lat": 19.935, "lon": 86.085, "villages": ["V18", "VK"]},
    {"id": "AMB-PURI", "name": "Puri coastal road", "lat": 19.840, "lon": 85.900, "villages": ["V01", "V10"]},
    {"id": "AMB-EAST", "name": "Eastern block", "lat": 20.040, "lon": 86.220, "villages": ["V22", "V24"]},
]

DEFAULT_RESOURCES = {"generators": 2, "ambulances": 3, "rescue_teams": 4, "telecom_units": 1}

# SYNTHETIC field-data snapshot at T+6h for the reach-gap detector.
FIELD_SNAPSHOT = {
    "V01": {"reports": 64, "verified_contacts": 2100, "shelter_checkins": 2600, "last_contact_h": 0.5},
    "V03": {"reports": 12, "verified_contacts": 540, "shelter_checkins": 700, "last_contact_h": 1.5},
    "V05": {"reports": 9, "verified_contacts": 380, "shelter_checkins": 520, "last_contact_h": 2.0},
    "V08": {"reports": 21, "verified_contacts": 900, "shelter_checkins": 1300, "last_contact_h": 1.0},
    "V10": {"reports": 18, "verified_contacts": 610, "shelter_checkins": 900, "last_contact_h": 2.5},
    "V12": {"reports": 14, "verified_contacts": 420, "shelter_checkins": 760, "last_contact_h": 3.0},
    "V14": {"reports": 11, "verified_contacts": 380, "shelter_checkins": 450, "last_contact_h": 3.5},
    "V16": {"reports": 6, "verified_contacts": 150, "shelter_checkins": 190, "last_contact_h": 4.0},
    "V18": {"reports": 15, "verified_contacts": 610, "shelter_checkins": 880, "last_contact_h": 2.0},
    "VK":  {"reports": 3, "verified_contacts": 42, "shelter_checkins": 0, "last_contact_h": 5.0},
    "V22": {"reports": 7, "verified_contacts": 260, "shelter_checkins": 310, "last_contact_h": 3.0},
    "V24": {"reports": 2, "verified_contacts": 35, "shelter_checkins": 20, "last_contact_h": 6.5},
    "V26": {"reports": 10, "verified_contacts": 700, "shelter_checkins": 500, "last_contact_h": 1.0},
}

EMERGENCY_NUMBER = "112"
