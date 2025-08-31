# app/db.py
from __future__ import annotations
import os
from datetime import datetime, date, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from supabase import create_client, Client  # pip install supabase
except Exception:  # pragma: no cover
    create_client = None
    Client = None  # type: ignore

_SUPA_URL = os.getenv("SUPABASE_URL")
_SUPA_ANON = os.getenv("SUPABASE_ANON_KEY")
_SUPA_SERVICE = os.getenv("SUPABASE_SERVICE_KEY")


def _client(service: bool = False) -> Optional["Client"]:
    if not create_client or not _SUPA_URL:
        return None
    key = _SUPA_SERVICE if service and _SUPA_SERVICE else _SUPA_ANON
    if not key:
        return None
    return create_client(_SUPA_URL, key)


# -------------------- Users --------------------
def get_user_by_handle(handle: str) -> Optional[Dict[str, Any]]:
    sb = _client()
    if not sb:
        return None
    res = sb.table("users").select("*").eq("handle", handle).limit(1).execute()
    return (res.data or [None])[0]


# -------------------- Classes --------------------
def get_classes_for_user(user_id: str) -> List[Dict[str, Any]]:
    sb = _client()
    if not sb:
        return []
    res = sb.table("classes").select("*").eq("user_id", user_id).eq("active", True).order("start_time").execute()
    return res.data or []


def get_classes_for_day(user_id: str, day_token: str) -> List[Dict[str, Any]]:
    """
    day_token: 'Sun','Mon','Tue','Wed','Thu','Fri','Sat'
    """
    sb = _client()
    if not sb:
        return []
    # text[] contains → use PostgREST filter: contains as array string
    res = sb.table("classes").select("*").eq("user_id", user_id).contains("days_of_week", [day_token]).eq("active", True).order("start_time").execute()
    return res.data or []


# -------------------- Notes --------------------
def get_latest_note_for_class(user_id: str, class_id: str) -> Optional[Dict[str, Any]]:
    sb = _client()
    if not sb:
        return None
    res = sb.table("notes").select("*").eq("user_id", user_id).eq("class_id", class_id).order("created_at", desc=True).limit(1).execute()
    return (res.data or [None])[0]


def get_notes_for_day(user_id: str, the_date: date) -> List[Dict[str, Any]]:
    sb = _client()
    if not sb:
        return []
    res = sb.table("notes").select("*").eq("user_id", user_id).eq("note_date", the_date.isoformat()).order("created_at", desc=True).execute()
    return res.data or []


# -------------------- Reminders --------------------
def get_reminders_for_date(user_id: str, the_date: date, class_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sb = _client()
    if not sb:
        return []
    q = sb.table("reminders").select("*").eq("user_id", user_id).eq("remind_date", the_date.isoformat()).eq("resolved", False)
    if class_id:
        q = q.eq("class_id", class_id)
    res = q.order("created_at").execute()
    return res.data or []


# -------------------- Sessions (optional MVP use) --------------------
def upsert_session(user_id: str, class_id: str, session_date: date, start_time: str, end_time: str, status: str = "upcoming") -> None:
    sb = _client(service=True)
    if not sb:
        return
    sb.table("sessions").upsert({
        "user_id": user_id,
        "class_id": class_id,
        "session_date": session_date.isoformat(),
        "start_time": start_time,
        "end_time": end_time,
        "status": status,
    }, on_conflict="user_id,class_id,session_date").execute()


def get_sessions_for_date(user_id: str, the_date: date) -> List[Dict[str, Any]]:
    sb = _client()
    if not sb:
        return []
    res = sb.table("sessions").select("*").eq("user_id", user_id).eq("session_date", the_date.isoformat()).order("start_time").execute()
    return res.data or []


def set_session_status(session_id: str, status: str) -> None:
    sb = _client(service=True)
    if not sb:
        return
    sb.table("sessions").update({"status": status}).eq("id", session_id).execute()


# -------------------- Events Log --------------------
def log_event(task: str, status: str, message: str = "", user_id: Optional[str] = None,
              class_id: Optional[str] = None, payload: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
    sb = _client(service=True)
    if not sb:
        print(f"[LOG:{task}:{status}] {message} (no supabase client)")
        return
    sb.table("events_log").insert({
        "task": task,
        "status": status,
        "message": message,
        "user_id": user_id,
        "class_id": class_id,
        "payload": payload or {},
        "error": error or None
    }).execute()


def already_sent(task: str, on_day: date) -> bool:
    sb = _client()
    if not sb:
        return False
    start = datetime.combine(on_day, time(0, 0)).isoformat()
    end = (datetime.combine(on_day, time(0, 0)) + timedelta(days=1)).isoformat()
    res = sb.table("events_log").select("id").eq("task", task).gte("created_at", start).lt("created_at", end).eq("status", "success").limit(1).execute()
    return bool(res.data)
