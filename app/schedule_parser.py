# app/schedule_parser.py
from __future__ import annotations
from datetime import date, datetime
from typing import List, Dict, Any
from .time_utils import combine_date_time, day_token

def build_sessions_for_date(classes: List[Dict[str, Any]], the_date: date) -> List[Dict[str, Any]]:
    """From weekly classes (days_of_week + start/end), build today's sessions."""
    token = day_token(the_date)
    sessions = []
    for c in classes:
        days = c.get("days_of_week") or []
        if token in days:
            start = str(c.get("start_time"))  # 'HH:MM:SS'
            end = str(c.get("end_time"))
            sessions.append({
                "class": c,
                "start_dt": combine_date_time(the_date, start[:5]),
                "end_dt": combine_date_time(the_date, end[:5]),
            })
    sessions.sort(key=lambda s: s["start_dt"])
    return sessions
