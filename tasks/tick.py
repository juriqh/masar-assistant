# tasks/tick.py
import os
from datetime import datetime, time
from app.time_utils import now_local, today_local, combine_date_time
from app.orchestrator import morning_digest, pre_class, post_class, end_of_day
from app import db

MORNING = os.getenv("MORNING_DIGEST_TIME", "07:00")
ENDDAY = os.getenv("END_OF_DAY_TIME", "20:00")

def _is_now(hhmm: str, slack_min: int = 2) -> bool:
    now = now_local()
    target = combine_date_time(now.date(), hhmm)
    delta = abs((now - target).total_seconds()) / 60.0
    return delta <= slack_min

if __name__ == "__main__":
    now = now_local()
    # Morning digest (once per day)
    if _is_now(MORNING) and not db.already_sent("morning_digest", now.date()):
        morning_digest()

    # Pre-class check (windowed)
    pre_class()

    # Post-class check (windowed)
    post_class()

    # End-of-day (once per day)
    if _is_now(ENDDAY) and not db.already_sent("end_of_day", now.date()):
        end_of_day()
