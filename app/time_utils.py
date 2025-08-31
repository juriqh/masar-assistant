# app/time_utils.py
from __future__ import annotations
import os
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

TZ = os.getenv("TZ_USER", "Asia/Riyadh")

DAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
DAYS_TOKEN = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
# If your DB uses Sun..Sat order, you can still map via weekday()

def now_local() -> datetime:
    return datetime.now(ZoneInfo(TZ))

def today_local() -> date:
    return now_local().date()

def tomorrow_local() -> date:
    return today_local() + timedelta(days=1)

def day_token(d: date) -> str:
    # Python: Monday=0 → 0..6
    idx = datetime(d.year, d.month, d.day).weekday()
    # Map Monday..Sunday to "Mon".."Sun"
    return DAYS_TOKEN[idx]

def combine_date_time(d: date, hhmm: str) -> datetime:
    h, m = [int(x) for x in hhmm.split(":")[:2]]
    return datetime(d.year, d.month, d.day, h, m, tzinfo=ZoneInfo(TZ))

def within_minutes(dt: datetime, minutes: int, reference: datetime) -> bool:
    delta = (dt - reference).total_seconds() / 60.0
    return 0 <= delta <= minutes

def ended_within_minutes(end_dt: datetime, minutes: int, reference: datetime) -> bool:
    delta = (reference - end_dt).total_seconds() / 60.0
    return 0 <= delta <= minutes

def fmt_hhmm(hhmm: str) -> str:
    return hhmm[:5]  # "09:00:00" -> "09:00"
