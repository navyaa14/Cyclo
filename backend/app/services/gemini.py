"""
Gemini wrapper.

- Uses the official `google-genai` SDK. Works with a Gemini API key (GEMINI_API_KEY / GOOGLE_API_KEY)
  or Vertex AI (GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION).
- Retries with exponential backoff.
- Structured JSON output via response_schema; callers still validate with Pydantic.
- `numbers_grounded()` rejects generated text that contains numbers not present in the facts.
"""
from __future__ import annotations

import os
import re
import time
import logging

log = logging.getLogger("cyclops.gemini")

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - SDK optional
    genai = None
    types = None

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_client = None


def enabled() -> bool:
    if genai is None or os.getenv("CYCLOPS_DISABLE_GEMINI") == "1":
        return False
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
                or os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true")


def status() -> dict:
    return {"enabled": enabled(), "model": MODEL if enabled() else None,
            "mode": ("vertex" if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true" else "api_key")
            if enabled() else "fallback (no Gemini credentials configured)"}


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


def _with_retries(fn, attempts=3, base_delay=0.8):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # network / quota / 5xx
            last = e
            log.warning("Gemini call failed (attempt %s/%s): %s", i + 1, attempts, e)
            time.sleep(base_delay * (2 ** i))
    raise last


def generate_json(prompt: str, schema, image_bytes: bytes | None = None, mime_type: str | None = None) -> str:
    """Returns raw JSON text. Caller validates."""
    contents = [prompt]
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/jpeg"))
    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.1)
    resp = _with_retries(lambda: _get_client().models.generate_content(model=MODEL, contents=contents, config=cfg))
    return resp.text


def generate_text(prompt: str, temperature: float = 0.2) -> str:
    cfg = types.GenerateContentConfig(temperature=temperature)
    resp = _with_retries(lambda: _get_client().models.generate_content(model=MODEL, contents=[prompt], config=cfg))
    return resp.text or ""


_NUM = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")


def _norm(n: str) -> str:
    n = n.replace(",", "")
    try:
        f = float(n)
        return str(int(f)) if f.is_integer() else str(round(f, 2))
    except ValueError:
        return n


def numbers_grounded(text: str, facts_text: str) -> tuple[bool, list]:
    """Every number in `text` must appear in `facts_text` (identifiers like PHC-7 count too)."""
    allowed = {_norm(n) for n in _NUM.findall(facts_text)}
    # translate Devanagari / Odia digits to ASCII before checking
    trans = str.maketrans("०१२३४५६७८९୦୧୨୩୪୫୬୭୮୯", "01234567890123456789")
    found = [_norm(n) for n in _NUM.findall(text.translate(trans))]
    extra = sorted({n for n in found if n not in allowed})
    return (len(extra) == 0, extra)
