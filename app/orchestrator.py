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

# ---------- ENV & CLIENTS ----------
def _env_get(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return v

def supa() -> Client:
    url = _env_get("SUPABASE_URL")
    key = _env_get("SUPABASE_KEY")  # anon key
    return create_client(url, key)

def discord_post(content: str, is_log: bool = False) -> None:
    url = os.getenv("DISCORD_WEBHOOK_LOG_URL") if is_log else os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        return
    try:
        requests.post(url, json={"content": content}, timeout=10)
    except Exception as e:
        print(f"[orchestrator] Discord post failed: {e}")

def _fmt_hhmm(t: str | None) -> str:
    return t[:5] if t else "--:--"

# ---------- USERS ----------
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
    res = ctx.table("users").select("id, handle").eq("active", True).limit(1).execute()
    rows = res.data or []
    if not rows:
        raise RuntimeError("No active user found and ACTIVE_USER not set.")
    return UserCtx(id=rows[0]["id"], handle=rows[0]["handle"])

# ---------- FETCH ----------
def _fetch_user_classes(ctx: Client, user_id: str) -> List[Dict[str, Any]]:
    res = (
        ctx.table("classes")
        .select("id, class_code, class_name, location, days_of_week, start_time, end_time, remind_before_minutes, active")
        .eq("user_id", user_id)
        .eq("active", True)
        .order("start_time")
        .execute()
    )
    return res.data or []

def _day_tokens(dt: datetime) -> List[str]:
    short = dt.strftime("%a")   # Mon
    full  = dt.strftime("%A")   # Monday
    ar = {
        "Sun": ["الأحد","الاحد","أحد"],
        "Mon": ["الإثنين","الاثنين","اثنين"],
        "Tue": ["الثلاثاء"],
        "Wed": ["الأربعاء","الاربعاء"],
        "Thu": ["الخميس"],
        "Fri": ["الجمعة"],
        "Sat": ["السبت"],
    }
    toks = [short, full] + ar.get(short, [])
    return [t.lower() for t in toks]

def _matches_today(days_text: Optional[str], today_tokens_lower: List[str]) -> bool:
    if not days_text:
        return False
    txt = str(days_text).lower()
    return any(tok in txt for tok in today_tokens_lower)

def _title(r: Dict[str, Any]) -> str:
    t = (r.get("class_name") or r.get("class_code") or "Class").strip()
    return t if t else "Class"

# ---------- DEDUPE LOG ----------
def _day_bounds_utc(target_ry: datetime) -> tuple[datetime, datetime]:
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

# ---------- MORNING DIGEST ----------
def morning_digest() -> None:
    ctx = supa()
    now_ry = datetime.now(RY)
    user = _active_user(ctx)

    if os.getenv("DRY_RUN","false").lower() != "true" and _already_sent_today(ctx, "morning_digest", now_ry):
        msg = f"MorningDigest skipped (already sent for {now_ry.date()}) — user={user.handle}"
        _log_event(ctx, "morning_digest", "skipped", msg)
        discord_post(f"🟨 {msg}", is_log=True)
        return

    tokens = _day_tokens(now_ry)
    rows = _fetch_user_classes(ctx, user.id)
    todays = [r for r in rows if _matches_today(r.get("days_of_week"), tokens)]

    seen = set()
    unique: List[Dict[str,Any]] = []
    for r in todays:
        key = (_title(r), r.get("start_time"), r.get("end_time"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    todays = sorted(unique, key=lambda r: ((r.get("start_time") or "99:99"), (r.get("end_time") or "99:99"), _title(r)))

    if not todays:
        discord_post("صباح الخير ☀️\nNo classes today 🎉")
        _log_event(ctx, "morning_digest", "sent", f"no-classes | user={user.handle}")
        return

    lines: List[str] = []
    for r in todays:
        start = _fmt_hhmm(r.get("start_time"))
        end   = _fmt_hhmm(r.get("end_time"))
        name  = _title(r)
        loc   = (r.get("location") or "").strip()
        lines.append(f"{start}–{end} — {name}" + (f" · {loc}" if loc else ""))

    discord_post("صباح الخير ☀️\n" + "\n".join(lines))
    _log_event(ctx, "morning_digest", "sent", f"{len(todays)} classes | user={user.handle}")
    discord_post(f"✅ MorningDigest {now_ry:%Y-%m-%d} — {len(todays)} classes (user={user.handle})", is_log=True)

# ---------- PRE-CLASS REMINDER ----------
def _preclass_key(class_id: int, start_dt_ry: datetime) -> str:
    return f"cid={class_id}|start={start_dt_ry:%Y-%m-%d %H:%M}"

def _preclass_already_sent(ctx: Client, key: str) -> bool:
    res = (
        ctx.table("events_log")
        .select("id")
        .eq("task", "preclass")
        .eq("status", "sent")
        .eq("message", key)
        .limit(1)
        .execute()
    )
    return bool(res.data)

def _mark_preclass_sent(ctx: Client, key: str) -> None:
    _log_event(ctx, "preclass", "sent", key)

def pre_class_reminder(asof: Optional[datetime] = None) -> None:
    ctx = supa()
    now_ry = (asof or datetime.now(RY)).astimezone(RY)
    user = _active_user(ctx)
    tokens = _day_tokens(now_ry)

    rows = _fetch_user_classes(ctx, user.id)
    todays = [r for r in rows if _matches_today(r.get("days_of_week"), tokens)]

    candidates: List[Dict[str, Any]] = []
    for r in todays:
        start_s = r.get("start_time")
        if not start_s:
            continue
        hh, mm = int(start_s[:2]), int(start_s[3:5])
        start_dt = now_ry.replace(hour=hh, minute=mm, second=0, microsecond=0)
        delta_min = int((start_dt - now_ry).total_seconds() // 60)
        remind_min = int(r.get("remind_before_minutes") or 30)
        if 0 <= delta_min <= remind_min:
            r["_start_dt"] = start_dt
            r["_delta_min"] = delta_min
            candidates.append(r)

    if not candidates:
        discord_post(f"ℹ️ No class inside reminder window @ {now_ry:%Y-%m-%d %H:%M} (Asia/Riyadh).", is_log=True)
        return

    cand = sorted(candidates, key=lambda r: (r["_delta_min"], r.get("start_time")))[0]
    start_dt = cand["_start_dt"]
    key = _preclass_key(int(cand["id"]), start_dt)
    if _preclass_already_sent(ctx, key):
        discord_post(f"🟨 Preclass already sent for {key}", is_log=True)
        return

    name = _title(cand)
    when = _fmt_hhmm(cand.get("start_time"))
    discord_post(f"تذكير ⏰\n{ name } بعد {cand['_delta_min']} دقيقة ({when})")
    _mark_preclass_sent(ctx, key)
    discord_post(f"✅ Preclass sent | {key}", is_log=True)

# ---------- POST-CLASS WRAP-UP ----------
def _postclass_key(class_id: int, end_dt_ry: datetime) -> str:
    return f"cid={class_id}|end={end_dt_ry:%Y-%m-%d %H:%M}"

def _postclass_already_sent(ctx: Client, key: str) -> bool:
    res = (
        ctx.table("events_log")
        .select("id")
        .eq("task", "postclass")
        .eq("status", "sent")
        .eq("message", key)
        .limit(1)
        .execute()
    )
    return bool(res.data)

def _mark_postclass_sent(ctx: Client, key: str) -> None:
    _log_event(ctx, "postclass", "sent", key)

def post_class_wrapup(asof: Optional[datetime] = None, window_min: int = 10) -> None:
    """
    If a class ended within the last `window_min` minutes (default 10),
    send a wrap-up prompt with a deterministic upload path.
    """
    ctx = supa()
    now_ry = (asof or datetime.now(RY)).astimezone(RY)
    user = _active_user(ctx)
    tokens = _day_tokens(now_ry)

    rows = _fetch_user_classes(ctx, user.id)
    todays = [r for r in rows if _matches_today(r.get("days_of_week"), tokens)]

    ended_recently: List[Dict[str, Any]] = []
    for r in todays:
        end_s = r.get("end_time")
        if not end_s:
            continue
        eh, em = int(end_s[:2]), int(end_s[3:5])
        end_dt = now_ry.replace(hour=eh, minute=em, second=0, microsecond=0)
        delta_min = int((now_ry - end_dt).total_seconds() // 60)
        if 0 <= delta_min <= window_min:
            r["_end_dt"] = end_dt
            r["_delta_min"] = delta_min
            ended_recently.append(r)

    if not ended_recently:
        discord_post(f"ℹ️ No class ended in last {window_min} min @ {now_ry:%Y-%m-%d %H:%M}.", is_log=True)
        return

    cand = sorted(ended_recently, key=lambda r: (r["_delta_min"], r.get("end_time")))[0]
    end_dt = cand["_end_dt"]
    key = _postclass_key(int(cand["id"]), end_dt)
    if _postclass_already_sent(ctx, key):
        discord_post(f"🟨 Postclass already sent for {key}", is_log=True)
        return

    name   = _title(cand)
    code   = (cand.get("class_code") or "").strip() or "Class"
    today  = end_dt.strftime("%Y-%m-%d")
    user_id = _active_user(ctx).id  # reuse

    # deterministic storage path for today's class
    upload_prefix = f"{user_id}/{today}/{code}/"  # e.g., 7972.../2025-09-01/1001/

    msg = (
        f"انتهت {name} ✅\n"
        f"تبين ترفعين الملخص/الملفات؟\n"
        f"المجلد لليوم: `notes/{upload_prefix}`\n"
        f"(شغّلي الرفع في Colab وبيتحفظ كل ملف هناك بنفس المجلد)"
    )
    discord_post(msg)
    _mark_postclass_sent(ctx, key)
    discord_post(f"✅ Postclass sent | {key}", is_log=True)
