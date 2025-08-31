# app/orchestrator.py
from __future__ import annotations
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
from . import db
from . import notifier as nt
from .time_utils import now_local, today_local, tomorrow_local, day_token, combine_date_time, within_minutes, ended_within_minutes, fmt_hhmm
from .schedule_parser import build_sessions_for_date
from .embeddings_rag import search_recent_notes

ACTIVE_USER = os.getenv("ACTIVE_USER", "fatoom")
PRE_CLASS_OFFSET = int(os.getenv("PRE_CLASS_OFFSET", "30"))
POST_CLASS_GRACE = int(os.getenv("POST_CLASS_GRACE", "5"))
MORNING_TIME = os.getenv("MORNING_DIGEST_TIME", "07:00")
END_DAY_TIME = os.getenv("END_OF_DAY_TIME", "20:00")


def _get_user() -> Optional[Dict[str, Any]]:
    return db.get_user_by_handle(ACTIVE_USER)


def morning_digest() -> None:
    user = _get_user()
    if not user:
        nt.log("morning_digest: no user")
        return
    today = today_local()
    if db.already_sent("morning_digest", today):
        return
    classes = db.get_classes_for_day(user["id"], day_token(today))
    reminders = db.get_reminders_for_date(user["id"], today, None)
    lines = []
    if classes:
        lines.append("**Today's classes:**")
        for c in classes:
            st = fmt_hhmm(str(c["start_time"]))
            en = fmt_hhmm(str(c["end_time"]))
            lines.append(f"- {c['class_code']} · {c['class_name']} · {st}–{en} @ {c.get('location','')}")
    else:
        lines.append("No classes today 🎉")

    if reminders:
        lines.append("")
        lines.append("**Reminders:**")
        for r in reminders:
            lines.append(f"• {r['message']}")

    msg = "صباح الخير ☀️\n" + "\n".join(lines)
    ok = nt.send(msg)
    db.log_event("morning_digest", "success" if ok else "fail", message="sent", user_id=user["id"])


def pre_class() -> None:
    user = _get_user()
    if not user:
        nt.log("pre_class: no user")
        return
    now = now_local()
    classes = db.get_classes_for_day(user["id"], day_token(now.date()))
    sessions = build_sessions_for_date(classes, now.date())

    for s in sessions:
        if within_minutes(s["start_dt"], PRE_CLASS_OFFSET, now):
            c = s["class"]
            # Pull last notes for this class (MVP: latest note)
            last_notes = search_recent_notes(user["id"], c["id"], limit=1)
            snippet = ""
            if last_notes:
                n = last_notes[0]
                title = n.get("title") or "previous notes"
                snippet = f"\n**Review:** {title}"
            # Any class-specific reminders for today
            rems = db.get_reminders_for_date(user["id"], now.date(), c["id"])
            rem_txt = ""
            if rems:
                rem_txt = "\n**Don't forget:** " + "; ".join([r["message"] for r in rems])

            st = fmt_hhmm(str(c["start_time"]))
            msg = f"🔔 {c['class_code']} starts in ≤{PRE_CLASS_OFFSET} min ({st}).{snippet}{rem_txt}"
            ok = nt.send(msg)
            db.log_event("pre_class", "success" if ok else "fail", message=f"{c['class_code']}", user_id=user["id"], class_id=c["id"])


def post_class() -> None:
    user = _get_user()
    if not user:
        nt.log("post_class: no user")
        return
    now = now_local()
    classes = db.get_classes_for_day(user["id"], day_token(now.date()))
    sessions = build_sessions_for_date(classes, now.date())
    for s in sessions:
        if ended_within_minutes(s["end_dt"], POST_CLASS_GRACE, now):
            c = s["class"]
            msg = (
                f"✅ {c['class_code']} finished.\n"
                "Do you want to upload notes/files now? I’ll file them under today’s date."
            )
            ok = nt.send(msg)
            db.log_event("post_class", "success" if ok else "fail", message=f"{c['class_code']}", user_id=user["id"], class_id=c["id"])

            # Peek next class today for bring-list
            after = [x for x in sessions if x["start_dt"] > s["start_dt"]]
            if after:
                nxt = after[0]["class"]
                rems = db.get_reminders_for_date(user["id"], now.date(), nxt["id"])
                if rems:
                    msg2 = f"🎒 Next: {nxt['class_code']} — bring: " + ", ".join([r["message"] for r in rems])
                    nt.send(msg2)


def end_of_day() -> None:
    user = _get_user()
    if not user:
        nt.log("end_of_day: no user")
        return
    today = today_local()
    classes = db.get_classes_for_day(user["id"], day_token(today))
    notes = db.get_notes_for_day(user["id"], today)

    lines = ["**Today summary:**"]
    if classes:
        lines.append("• Classes completed: " + ", ".join([c["class_code"] for c in classes]))
    else:
        lines.append("• No classes today.")

    if notes:
        lines.append("• Notes uploaded: " + ", ".join([n.get("title") or "untitled" for n in notes]))
    else:
        lines.append("• No notes uploaded today.")

    # Tomorrow preview
    tomorrow = tomorrow_local()
    tmr_classes = db.get_classes_for_day(user["id"], day_token(tomorrow))
    if tmr_classes:
        lines.append("")
        lines.append("**Tomorrow:**")
        for c in tmr_classes:
            st = fmt_hhmm(str(c["start_time"]))
            lines.append(f"- {c['class_code']} {st}")

        lines.append("\nWant me to remind you to bring anything for a class tomorrow?")

    ok = nt.send("\n".join(lines))
    db.log_event("end_of_day", "success" if ok else "fail", message="sent", user_id=user["id"])
