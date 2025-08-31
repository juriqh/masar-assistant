# app/ocr.py
# ---------------------------------------------
# Arabic-aware schedule OCR + normalization
# - Downloads image from Supabase Storage
# - Uses Gemini to extract JSON
# - Normalizes Arabic/English day names + digits
# - Normalizes times like "8.0-9.50" -> "08:00–09:50"
# - Merges per-day blocks into per-slot entries
# - Safe upsert: allows multiple time slots per class_code
# ---------------------------------------------
from __future__ import annotations
import os, re, json, mimetypes
from typing import Any, Dict, List, Tuple, Optional, Iterable

from . import db
from . import notifier as nt

# ---- Supabase Storage helpers ----
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
    """
    Accepts either:
      - "bucket/relative/key.png"
      - "relative/key.png" (assumes bucket='schedules')
      - "key.png"         (assumes bucket='schedules')
    Returns: (bucket, relative_key)
    """
    parts = file_path.split("/", 1)
    if len(parts) == 1:
        return "schedules", parts[0]
    # If first token is a known bucket, use it
    bucket, rest = parts[0], parts[1]
    return bucket, rest

def download_bytes(file_path: str) -> Tuple[bytes, str]:
    sb = _sb()
    if not sb:
        raise RuntimeError("No Supabase client for storage")
    bucket, rel = _bucket_and_path(file_path)
    data = sb.storage.from_(bucket).download(rel)
    mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
    return data, mime

# ---- Arabic/English normalization ----

# Arabic-Indic digits → ASCII
_AR_NUM = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Day maps (multiple spellings)
_DAY_MAP = {
    # Arabic full
    "الأحد": "Sun", "الاحد": "Sun", "اﻷحد": "Sun", "الأحد": "Sun", "اﻷحد": "Sun", "أحد": "Sun", "احد": "Sun",
    "الاثنين": "Mon", "الإثنين": "Mon", "الاثنين": "Mon", "اثنين": "Mon",
    "الثلاثاء": "Tue", "ثلاثاء": "Tue",
    "الأربعاء": "Wed", "الاربعاء": "Wed", "اربعاء": "Wed",
    "الخميس": "Thu",
    "الجمعة": "Fri", "جمعة": "Fri",
    "السبت": "Sat", "سبت": "Sat",
    # Arabic short (common headings)
    "الاحد": "Sun", "الاثنين": "Mon", "الثلاثاء": "Tue", "الاربعاء": "Wed", "الخميس": "Thu", "الجمعة": "Fri", "السبت": "Sat",
    # English fallbacks
    "sun": "Sun", "mon": "Mon", "tue": "Tue", "tues": "Tue", "wed": "Wed", "thu": "Thu", "thur": "Thu", "thur.": "Thu",
    "fri": "Fri", "sat": "Sat",
}

_DAY_ORDER = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]

def _normalize_day_token(tok: str) -> Optional[str]:
    if not tok:
        return None
    t = tok.strip().translate(_AR_NUM)
    t = re.sub(r"[\u200f\u200e]", "", t)  # remove RTL/LTR marks
    t_low = t.lower()
    # direct map
    if t_low in _DAY_MAP:
        return _DAY_MAP[t_low]
    # remove "ال" prefix and try again
    if t_low.startswith("ال"):
        x = t_low[2:]
        if x in _DAY_MAP:
            return _DAY_MAP[x]
    # capitalized English abbreviations
    cap = t[:3].title()
    if cap in _DAY_ORDER:
        return cap
    return None

def _normalize_days(value: Any) -> List[str]:
    """
    Accepts: list of tokens, string with commas/spaces, etc.
    Returns: list of unique day tokens in Sun..Sat order.
    """
    tokens: List[str] = []
    if isinstance(value, list):
        candidates = value
    elif isinstance(value, str):
        value = value.replace("،", ",")  # Arabic comma
        candidates = re.split(r"[,\s/|]+", value)
    else:
        candidates = []

    for c in candidates:
        d = _normalize_day_token(str(c))
        if d and d not in tokens:
            tokens.append(d)

    # keep canonical order
    tokens = [d for d in _DAY_ORDER if d in tokens]
    return tokens

def _to_hhmm(num_str: str) -> Optional[str]:
    """
    Converts "8", "8.0", "8.00", "9.50", "09:00", "10-50" etc. to "HH:MM".
    Rules:
      - dot "." → decimal minutes: .00 → :00, .50 → :50, .5 → :30 (fallback)
      - colon ":" → already minutes
    """
    s = (num_str or "").strip()
    if not s:
        return None
    s = s.translate(_AR_NUM)
    s = s.replace("٫", ".").replace(":", ":").replace("‒", "-").replace("–", "-").replace("—", "-")
    m = re.match(r"^\s*(\d{1,2})(?:[:\.](\d{1,2}))?\s*$", s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = m.group(2)
    if mm is None:
        minutes = 0
    else:
        # If it's like ".50" treat as 50; ".5" treat as 30 as a pragmatic fallback
        mm_i = int(mm)
        if len(mm) == 1:
            minutes = 30  # ".5" case
        else:
            minutes = mm_i if mm_i in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55) else mm_i
            if mm_i == 50:  # common in your schedule
                minutes = 50
    return f"{hh:02d}:{minutes:02d}"

def _normalize_time_span(val: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Accepts "8.0-9.50", "08:00–09:50", "8 - 9.5" etc.
    Returns ("HH:MM","HH:MM")
    """
    if not val:
        return (None, None)
    v = val.translate(_AR_NUM)
    v = v.replace("–", "-").replace("—", "-").replace("‒", "-")
    m = re.match(r"^\s*([0-9:\.]+)\s*-\s*([0-9:\.]+)\s*$", v)
    if not m:
        # sometimes it's "8.0–9.50" without dashes due to OCR; try space split
        parts = re.split(r"\s*[-–—]\s*", v)
        if len(parts) == 2:
            start = _to_hhmm(parts[0])
            end = _to_hhmm(parts[1])
            return (start, end)
        return (_to_hhmm(v), None)
    start = _to_hhmm(m.group(1))
    end = _to_hhmm(m.group(2))
    return (start, end)

def _canon_slot_key(code: str, start: str, end: str, days: Iterable[str]) -> str:
    d = [x for x in _DAY_ORDER if x in set(days)]
    return f"{code.strip()}::{start}::{end}::{'|'.join(d)}"

def _merge_slots(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge same class_code + same time into one entry with combined days.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for it in items:
        code = (it.get("class_code") or "").strip()
        st = it.get("start_time") or ""
        en = it.get("end_time") or ""
        days = _normalize_days(it.get("days_of_week") or [])
        if not code or not st or not en or not days:
            # skip incomplete
            continue
        key = f"{code}::{st}::{en}"
        if key not in merged:
            merged[key] = {
                "class_code": code,
                "class_name": (it.get("class_name") or "").strip(),
                "location": (it.get("location") or "").strip(),
                "start_time": st,
                "end_time": en,
                "days_of_week": [],
            }
        acc = merged[key]
        # merge days uniquely in canonical order
        acc_days = _normalize_days(acc.get("days_of_week"))
        for d in days:
            if d not in acc_days:
                acc_days.append(d)
        acc["days_of_week"] = [x for x in _DAY_ORDER if x in acc_days]
        # prefer non-empty names/locations
        if not acc["class_name"] and it.get("class_name"):
            acc["class_name"] = it["class_name"].strip()
        if not acc["location"] and it.get("location"):
            acc["location"] = it["location"].strip()
    return list(merged.values())

# ---- Gemini OCR ----
from google import genai

_PROMPT = (
    "You are extracting a weekly university class schedule from the image.\n"
    "IMPORTANT:\n"
    "- The timetable may be in Arabic (RTL). Day columns likely are: الأحد, الاثنين, الثلاثاء, الأربعاء, الخميس.\n"
    "- Times might look like '8.0-9.50' (means 08:00–09:50). Convert to 24h HH:MM.\n"
    "- Output JSON ONLY with this schema:\n"
    "{ \"classes\": [ {\n"
    "  \"class_code\": string,\n"
    "  \"class_name\": string,\n"
    "  \"location\": string,\n"
    "  \"days_of_week\": [\"Sun\",\"Mon\",\"Tue\",\"Wed\",\"Thu\",\"Fri\",\"Sat\"],\n"
    "  \"start_time\": \"HH:MM\",\n"
    "  \"end_time\": \"HH:MM\"\n"
    "} ] }\n"
    "- If a class appears at MULTIPLE time slots, create a SEPARATE entry per time slot (same class_code allowed multiple times).\n"
    "- Map Arabic day names to: Sun,Mon,Tue,Wed,Thu,Fri,Sat.\n"
    "- If a slot spans several days (same time), include all those days in `days_of_week`.\n"
    "- Do NOT include prose; JSON only."
)

def gemini_extract_schedule(image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
    """
    Returns:
      {
        "text": <raw model text>,
        "json": <parsed JSON or None>,
        "normalized": <list of normalized slot dicts>
      }
    """
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    contents = [{"role": "user", "parts": [
        {"text": _PROMPT},
        {"inline_data": {"mime_type": mime_type, "data": image_bytes}},
    ]}]
    resp = client.models.generate_content(model="gemini-1.5-flash", contents=contents)
    raw = getattr(resp, "output_text", None) or str(resp)

    parsed = None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            parsed = {"classes": parsed}
    except Exception:
        try:
            s = raw.find("{")
            e = raw.rfind("}")
            if s != -1 and e != -1:
                parsed = json.loads(raw[s:e+1])
        except Exception:
            parsed = None

    norm_items: List[Dict[str, Any]] = []
    if parsed and isinstance(parsed, dict):
        for item in (parsed.get("classes") or []):
            code = (item.get("class_code") or "").translate(_AR_NUM).strip()
            name = (item.get("class_name") or "").strip()
            loc  = (item.get("location") or "").strip()
            days = _normalize_days(item.get("days_of_week"))
            # Time can be a single "8.0-9.50" string OR already split
            st = item.get("start_time")
            en = item.get("end_time")
            if (not st or not en) and isinstance(item.get("time"), str):
                st, en = _normalize_time_span(item["time"])
            if isinstance(st, str) and isinstance(en, str):
                st = _to_hhmm(st)
                en = _to_hhmm(en)
            else:
                # Try to parse if provided as "8.0-9.50" in some other key
                if isinstance(item.get("time_span"), str):
                    st, en = _normalize_time_span(item["time_span"])
            if st and en and code and days:
                norm_items.append({
                    "class_code": code,
                    "class_name": name,
                    "location": loc,
                    "days_of_week": days,
                    "start_time": st,
                    "end_time": en,
                })

    # Merge same code + same time across repeated per-day rows
    norm_items = _merge_slots(norm_items)

    return {"text": raw, "json": parsed, "normalized": norm_items}

# ---- Upsert into classes (allows multiple slots per code) ----

def upsert_classes_from_parsed(user_id: str, parsed_json: Dict[str, Any]) -> Dict[str, int]:
    """
    Accepts either raw parsed JSON (with 'classes') or the 'normalized' list from gemini_extract_schedule.
    Writes rows into `classes`. A user may have the same class_code at multiple time slots.
    Uniqueness: (class_code, start_time, end_time, days_of_week as set)
    """
    # If caller passes the normalized list directly under 'normalized'
    items = parsed_json.get("normalized")
    if not items:
        items = parsed_json.get("classes") or []
    if not isinstance(items, list):
        items = []

    # Normalize all again to be safe
    norm: List[Dict[str, Any]] = []
    for it in items:
        code = (it.get("class_code") or "").translate(_AR_NUM).strip()
        name = (it.get("class_name") or "").strip()
        loc  = (it.get("location") or "").strip()
        days = _normalize_days(it.get("days_of_week"))
        st   = it.get("start_time")
        en   = it.get("end_time")
        if isinstance(st, str) and isinstance(en, str):
            st = _to_hhmm(st)
            en = _to_hhmm(en)
        elif isinstance(it.get("time"), str):
            st, en = _normalize_time_span(it["time"])
        if code and st and en and days:
            norm.append({"class_code": code, "class_name": name, "location": loc,
                         "start_time": st, "end_time": en, "days_of_week": days})

    # Merge by (code,start,end) and combine days
    norm = _merge_slots(norm)

    # Fetch existing to compute uniqueness
    existing = db.get_classes_for_user(user_id)
    seen: set[str] = set()
    for ex in existing:
        key = _canon_slot_key(
            ex.get("class_code",""),
            str(ex.get("start_time"))[:5],
            str(ex.get("end_time"))[:5],
            _normalize_days(ex.get("days_of_week") or []),
        )
        seen.add(key)

    inserted, skipped, updated = 0, 0, 0
    sb = db._client(service=True)  # type: ignore
    if not sb:
        raise RuntimeError("No Supabase client (service) for upsert")

    for it in norm:
        key = _canon_slot_key(it["class_code"], it["start_time"], it["end_time"], it["days_of_week"])
        if key in seen:
            # Optional: try to update name/location if blank in DB
            skipped += 1
            continue
        payload = {
            "user_id": user_id,
            "class_code": it["class_code"],
            "class_name": it["class_name"],
            "location": it["location"],
            "days_of_week": it["days_of_week"],
            "start_time": it["start_time"],
            "end_time": it["end_time"],
            "active": True,
        }
        sb.table("classes").insert(payload).execute()
        seen.add(key)
        inserted += 1

    return {"inserted": inserted, "skipped": skipped, "updated": updated}
