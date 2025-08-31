# app/orchestrator.py
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

import requests
from supabase import create_client, Client

RY = ZoneInfo("Asia/Riyadh")

# ------------------------ Utilities & Clients ------------------------

def _env_get(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return v

def supa() -> Client:
    url = _env_get("SUPABASE_URL")
    key = _env_get("SUPABASE_KEY")
    return create_client(url, key)

def discord_post(content: str, is_log: bool = False) -> None:
    url = os.getenv("DISCORD_WEBHOOK_LOG_URL") if is_log else os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        # Silently no-op if webhook missing (useful during DRY runs)
        return
    try:
        requests.post(url, json={"content": content}, timeout=10)
    except Exception as e:
        # Last-ditch: don’t crash the job because of Discord
        print(f"[orchestrator] Discord post failed: {e}")

def _fmt_hhmm(t: str | None) -> str:
    # Supabase returns '08:00:00' strings for time columns
    if not t:
        return "--:--"
    return t[:5]

def _day_tokens(dt: datetime) -> List[str]:
    short = dt.strftime("%a")      # 'Mon'
    full  = dt.strftime("%A")      # 'Monday'
    # Arabic variants commonly seen
    ar = {
        "Sun": ["الأحد", "الاحد", "أحد"],
        "Mon": ["الإثنين", "الاثنين", "اثنين"],
        "Tue": ["الثلاثاء"],
        "Wed": ["الأربعاء", "الاربعاء"],
        "Thu": ["الخميس"],
        "Fri": ["الجمعة"],
        "Sat": ["السبت"],
    }
    toks = [short, full]
    toks.extend(ar.get(short, []))
    # Lowercase everything for matching
    return [t.lower() for t in toks]

@dataclass
class UserCtx:
    id: str
    handle: str

def _active_user(ctx: Client) -> UserCtx:
    handle = os.getenv("ACTIVE_USER", "").strip()
    if handle:
        res = ctx.table("users").select("id, handle").eq("handle", handle).limit(1).execute()
        rows = res.data or []
        if rows:
            return UserCtx(id=rows[0]["id"], handle=rows[0]["handle"])
        raise RuntimeError(f"ACTIVE_USER '{handle}' not found in users table.")
    # Fallback: first active user
    res = ctx.table("users").select("id, handle").eq("active", True).limit(1).execute()
    rows = res.data or []
    if not rows:
        raise RuntimeError("No active user found and ACTIVE_USER not set.")
    return UserCtx(id=rows[0]["id"], handle=rows[0]["handle"])

def _fetch_user_classes(ctx: Client, user_id: str) -> List[Dict[str, Any]]:
    res = (
        ctx.table("classes")
        .select("id, class_code, class_name, location, days_of_week, start_time, end_time, active")
        .eq("user_id", user_id)
        .eq("active", True)
        .order("start_time")  # server-side sort
        .execute()
    )
    return res.data or []

def _matches_today(days_text: Optional[str], today_tokens_lower: List[str]) -> bool:
    if not days_text:
        return False
    txt = str(days_text).lower()
    # Accept any token present, tolerate separators (commas, slashes, spaces)
    return any(tok in txt for tok in today_tokens_lower)

# ------------------------ Dedupe (per-day) ------------------------

def _day_bounds_utc(target_ry: datetime) -> tuple[datetime, datetime]:
    # Day in Riyadh → map to UTC bounds for created_at filtering
    start_ry = target_ry.replace(hour=0, minute=0, second=0, microsecond=0)
    end_ry = start_ry + timedelta(days=1)
    return start_ry.astimezone(timezone.utc), end_ry.astimezone(timezone.utc)

def _already_sent_today(ctx: Client, task: str, target_ry: datetime) -> bool:
    start_utc, end_utc = _day_bounds_utc(target_ry)
    res = (
        ctx.table("events_log")
        .select("id")
        .eq("task", task)
        .gte("created_at", start_utc.isoformat())
        .lt("created_at", end_utc.isoformat())
        .limit(1)
        .execute()
    )
    return bool(res.data)

def _log_event(ctx: Client, task: str, status: str, message: str) -> None:
    try:
        ctx.table("events_log").insert({"task": task, "status": status, "message": message}).execute()
    except Exception as e:
        print(f"[orchestrator] events_log insert failed: {e}")

# ------------------------ Morning Digest ------------------------

def morning_digest(force: bool = False, asof: Optional[datetime] = None) -> None:
    """
    Send a morning schedule message for the *whole day* (no upcoming filter).
    - force: bypass per-day dedupe
    - asof: test a specific Riyadh datetime (timezone-aware or naive local string you pass in)
    """
    ctx = supa()
    now_ry = (asof or datetime.now(RY)).astimezone(RY)

    try:
        user = _active_user(ctx)
    except Exception as e:
        discord_post(f"⚠️ MorningDigest: user lookup failed — {e}", is_log=True)
        raise

    if not force and _already_sent_today(ctx, "morning_digest", now_ry):
        msg = f"MorningDigest skipped (already sent for {now_ry.date()}) — user={user.handle}"
        _log_event(ctx, "morning_digest", "skipped", msg)
        discord_post(f"🟨 {msg}", is_log=True)
        return

    tokens = _day_tokens(now_ry)  # e.g., ['mon','monday','الإثنين','الاثنين','اثنين']
    rows = _fetch_user_classes(ctx, user.id)
    todays = [r for r in rows if _matches_today(r.get("days_of_week"), tokens)]

    if not todays:
        text = "صباح الخير ☀️\nNo classes today 🎉"
        discord_post(text)
        _log_event(ctx, "morning_digest", "sent", f"no-classes | user={user.handle}")
        return

    # Format lines
    lines = []
    for r in todays:
        start = _fmt_hhmm(r.get("start_time"))
        end = _fmt_hhmm(r.get("end_time"))
        name = (r.get("class_name") or "").strip()
        code = (r.get("class_code") or "").strip()
        title = name if name else code if code else "Class"
        loc = (r.get("location") or "").strip()
        if loc:
            lines.append(f"{start}–{end} — {title} · {loc}")
        else:
            lines.append(f"{start}–{end} — {title}")

    header = "صباح الخير ☀️\n"
    body = "\n".join(lines)
    discord_post(header + body)
    _log_event(ctx, "morning_digest", "sent", f"{len(todays)} classes | user={user.handle}")
    discord_post(f"✅ MorningDigest sent for {now_ry.strftime('%Y-%m-%d')} — {len(todays)} classes (user={user.handle})", is_log=True)

# ------------------------ (Optional) Other hooks you might call later ------------------------

def pre_class_reminder(asof: Optional[datetime] = None) -> None:
    """Example: send a T-minus reminder based on `remind_before_minutes` (kept minimal)."""
    ctx = supa()
    now_ry = (asof or datetime.now(RY)).astimezone(RY)
    user = _active_user(ctx)
    tokens = _day_tokens(now_ry)
    rows = _fetch_user_classes(ctx, user.id)
    todays = [r for r in rows if _matches_today(r.get("days_of_week"), tokens)]

    # Find next class that hasn't started yet and is within its reminder window
    for r in todays:
        start_s = r.get("start_time")
        if not start_s:
            continue
        # Build today's datetime for that start time in Riyadh
        hh, mm = int(start_s[:2]), int(start_s[3:5])
        start_dt = now_ry.replace(hour=hh, minute=mm, second=0, microsecond=0)
        delta_min = int((start_dt - now_ry).total_seconds() // 60)
        remind_min = int(r.get("remind_before_minutes") or 0)
        if 0 <= delta_min <= max(remind_min, 30):  # default 30 if not set
            name = (r.get("class_name") or r.get("class_code") or "Class").strip() or "Class"
            text = f"تذكير ⏰\n{delta_min} دقيقة وتبدأ {name} ({_fmt_hhmm(start_s)})"
            discord_post(text)
            return

def end_of_day_summary(asof: Optional[datetime] = None) -> None:
    """Stub: summarize attended/uploaded notes, and preview tomorrow (fill when your DB is ready)."""
    now_ry = (asof or datetime.now(RY)).astimezone(RY)
    discord_post(f"ملخص اليوم 📘 ({now_ry.strftime('%Y-%m-%d')}) — coming soon.")
