"""Minimal .env loader (no extra dependency). Existing environment variables always win,
so Cloud Run secrets override any local file. Never commit .env."""
from __future__ import annotations

import os
from pathlib import Path


def load_env():
    here = Path(__file__).resolve()
    for path in (here.parents[2] / ".env", here.parents[1] / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val
