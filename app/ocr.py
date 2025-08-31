# app/ocr.py
from __future__ import annotations
import base64, json, mimetypes, os
from typing import Any, Dict, List, Optional, Tuple

from . import db
from . import notifier as nt

# Supabase storage download
try:
    from supabase import create_client
except Exception:
    create_client = None

_SUPA_URL = os.getenv("SUPABASE_URL")
_SUPA_SERVICE = os.getenv("SUPABASE_SERVICE_KEY")

def _sb():
    if not create_client or not _SUPA_URL or not _SUPA_SERVICE:
        return None
    return create_client(_SUPA_URL, _SUPA_SERVICE)

def _bucket_and_path(file_path: str) -> Tuple[str, str]:
    # expects like "schedules/handle/2025-09-01/schedule.png"
    parts = file_path.split("/", 1)
    if len(parts) == 1:
        # assume default bucket 'schedules'
        return "schedules", parts[0]
    return parts[0], parts[1]

def download_bytes(file_path: str) -> Tuple[bytes, str]:
    sb = _sb()
    if not sb:
        raise RuntimeError("No Supabase client for storage")
    bucket, rel = _bucket_and_path(file_path)
    data = sb.storage.from_(bucket).download(rel)
    mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
    return data, mime

# -------- Gemini OCR --------
from google import genai

def gemini_extract_schedule(image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
    """
    Returns {"text": <raw ocr/insight>, "json": <parsed list or None>}
    """
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = (
        "You are extracting a university class schedule from an image."
        " Return ONLY JSON, no prose. Schema:\n"
        "{ \"classes\": [ {"
        "  \"class_code\": string,"
        "  \"class_name\": string,"
        "  \"location\": string,"
        "  \"days_of_week\": [\"Sun\",\"Mon\",\"Tue\",\"Wed\",\"Thu\",\"Fri\",\"Sat\"],"
        "  \"start_time\": \"HH:MM\","
        "  \"end_time\": \"HH:MM\""
        "} ] }\n"
        "If something is missing, infer sensibly or leave empty string. Use 24h times."
    )
    parts = [
        {"text": prompt},
        {"inline_data": {"mime_type": mime_type, "data": image_bytes}},
    ]
    resp = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=[{"role": "user", "parts": parts}],
    )
    raw = getattr(resp, "output_text", None) or str(resp)
    parsed = None
    try:
        # try strict JSON
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            parsed = {"classes": parsed}
    except Exception:
        # try to snip first {...} block
        try:
            s = raw.find("{")
            e = raw.rfind("}")
            if s != -1 and e != -1:
                parsed = json.loads(raw[s : e + 1])
        except Exception:
            parsed = None
    return {"text": raw, "json": parsed}

def upsert_classes_from_parsed(user_id: str, parsed_json: Dict[str, Any]) -> Dict[str, int]:
    """
    Writes classes if not already present for this user.
    Returns counts: {"inserted": X, "skipped": Y}
    """
    classes = parsed_json.get("classes") or []
    existing = {c["class_code"]: c for c in db.get_classes_for_user(user_id)}
    ins, skip = 0, 0
    for item in classes:
        code = (item.get("class_code") or "").strip()
        if not code:
            skip += 1
            continue
        if code in existing:
            skip += 1
            continue
        payload = {
            "user_id": user_id,
            "class_code": code,
            "class_name": (item.get("class_name") or "").strip(),
            "location": (item.get("location") or "").strip(),
            "days_of_week": item.get("days_of_week") or [],
            "start_time": (item.get("start_time") or "00:00"),
            "end_time": (item.get("end_time") or "00:00"),
            "active": True,
        }
        sb = db._client(service=True)  # type: ignore
        if not sb:
            raise RuntimeError("No Supabase client (service) for upsert")
        sb.table("classes").insert(payload).execute()
        ins += 1
    return {"inserted": ins, "skipped": skip}
