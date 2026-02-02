import csv
import io
import json
import os
import re
from typing import Dict, Optional

from openai import OpenAI


# -----------------------------
# Secrets helper
# -----------------------------
def _get_secret(name: str):
    """
    Works on Streamlit Cloud (st.secrets) and locally (.env / env vars).
    """
    try:
        import streamlit as st  # noqa: F401
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)


# ============================================================
# CSV helpers (bulk override mode)
# ============================================================

def make_csv_template(filenames: list[str]) -> bytes:
    """
    Produces a CSV template for bulk metadata entry.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["filename", "source_url", "venue_name", "ensemble_name", "performance_date"]
    )
    for fn in filenames:
        writer.writerow([fn, "", "", "", ""])
    return buf.getvalue().encode("utf-8")


def parse_metadata_csv(csv_bytes: bytes) -> Dict[str, Dict]:
    """
    Parses uploaded CSV and returns:
      { filename: {source_url, venue_name, ensemble_name, performance_date} }
    """
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    required = {"filename", "source_url", "venue_name", "ensemble_name", "performance_date"}
    headers = set(reader.fieldnames or [])
    if not required.issubset(headers):
        raise ValueError(f"CSV must include headers: {sorted(required)}")

    out: Dict[str, Dict] = {}
    for row in reader:
        fn = (row.get("filename") or "").strip()
        if not fn:
            continue
        out[fn] = {
            "source_url": (row.get("source_url") or "").strip() or None,
            "venue_name": (row.get("venue_name") or "").strip() or None,
            "ensemble_name": (row.get("ensemble_name") or "").strip() or None,
            "performance_date": (row.get("performance_date") or "").strip() or None,
        }
    return out


def merge_metadata(
    filename: str,
    auto: Optional[Dict] = None,
    csv_data: Optional[Dict[str, Dict]] = None,
    overrides: Optional[Dict] = None,
) -> Dict:
    """
    Merge priority (highest wins):
      overrides > csv row > auto

    Note:
      - We keep returning the legacy keys.
      - If autodetect adds source_url_display/source_url_canonical, they flow through via auto,
        but CSV/overrides can still win on source_url.
    """
    auto = auto or {}
    overrides = overrides or {}
    row = (csv_data or {}).get(filename, {}) if csv_data else {}

    def pick(key: str):
        return (
            overrides.get(key)
            or row.get(key)
            or auto.get(key)
            or None
        )

    merged = {
        "source_url": pick("source_url"),
        "venue_name": pick("venue_name"),
        "ensemble_name": pick("ensemble_name"),
        "performance_date": pick("performance_date"),
    }

    # pass through optional extras from auto (safe if ignored downstream)
    if auto.get("source_url_display"):
        merged["source_url_display"] = auto.get("source_url_display")
    if auto.get("source_url_canonical"):
        merged["source_url_canonical"] = auto.get("source_url_canonical")

    return merged


# ============================================================
# AI metadata auto-detect (all pages)
# ============================================================

# Broader regex: captures https://..., www..., and scheme-less domain/path.
URL_ANY_REGEX = re.compile(
    r"(?P<url>"
    r"(?:https?://|www\.)[^\s)>\]]+"
    r"|"
    r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s)>\]]+)?"
    r")",
    re.IGNORECASE,
)


def _normalize_urlish(url: str) -> str:
    """
    Normalize to display form: domain/path (no scheme, no www, no trailing slash), lowercase.
    """
    u = (url or "").strip()
    u = u.strip(" \t\r\n'\"()[]{}<>.,;")
    u = re.sub(r"^https?://", "", u, flags=re.I)
    u = re.sub(r"^www\.", "", u, flags=re.I)
    u = u.rstrip("/")
    return u.lower()


def _to_canonical(url_display: str) -> str:
    """
    Convert display form domain/path -> https://domain/path
    """
    u = (url_display or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, flags=re.I):
        u = "https://" + u.lstrip("/")
    return u.rstrip(".,);]")


_AUTODETECT_SYSTEM = (
    "You extract structured metadata from arts review / evidence PDFs for USCIS O-1 petitions. "
    "Return ONLY valid JSON. If a field is not found, return an empty string for that field."
)

_AUTODETECT_USER = """Extract metadata from the following document text.

Return JSON with keys:
- source_url
- venue_name
- ensemble_name
- performance_date

Guidelines:
- source_url: a URL visible in the document (prefer the publication URL; prefer the URL shown near the top of page 1 if present, not the print footer).
- performance_date: the date of the performance/event (as written in the document).
- venue_name: venue / hall / festival / organisation hosting the performance.
- ensemble_name: orchestra/ensemble/choir/company performing (if stated).

DOCUMENT TEXT:
{text}
"""


def autodetect_metadata(
    document_text: str,
    *,
    model: Optional[str] = None,
    max_chars: int = 25000,
    debug: bool = False,
) -> Dict:
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    chosen_model = model or _get_secret("OPENAI_MODEL") or "gpt-4o-mini"
    client = OpenAI(api_key=api_key)

    text = (document_text or "")
    prompt = _AUTODETECT_USER.format(text=text[:max_chars])

    data = {}
    try:
        resp = client.chat.completions.create(
            model=chosen_model,
            messages=[
                {"role": "system", "content": _AUTODETECT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as e:
        print(f"[autodetect_metadata] Error: {e}")
        if debug:
            raise
        data = {}

    def s(key: str) -> str:
        val = data.get(key, "")
        return str(val or "").strip()

    # URL from model (may be canonical or display)
    url_raw = s("source_url")

    # Fallback: capture scheme-less too (important for header URLs)
    if not url_raw:
        m = URL_ANY_REGEX.search(text)
        if m:
            url_raw = m.group("url").strip().rstrip(".,);]")

    # Produce both forms for downstream matching/scoring.
    url_display = _normalize_urlish(url_raw) if url_raw else ""
    url_canonical = _to_canonical(url_display) if url_display else ""

    return {
        # Legacy key: keep it canonical so CSV remains consistent
        "source_url": url_canonical or url_raw or "",
        # Extras: used by the highlighter to find the header occurrence
        "source_url_display": url_display,
        "source_url_canonical": url_canonical,
        "venue_name": s("venue_name"),
        "ensemble_name": s("ensemble_name"),
        "performance_date": s("performance_date"),
    }
