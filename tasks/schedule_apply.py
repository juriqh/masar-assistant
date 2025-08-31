# tasks/schedule_apply.py
import os, json
from app import notifier as nt
from app import db
from app.ocr import upsert_classes_from_parsed

ACTIVE = (os.getenv("ACTIVE_USER", "fatoom") or "fatoom").strip()

def _get_user():
    return db.get_user_by_handle(ACTIVE)

if __name__ == "__main__":
    user = _get_user()
    if not user:
        nt.log("schedule_apply: no user")
        raise SystemExit(0)

    sb = db._client(service=True)  # type: ignore
    res = (
        sb.table("schedule_uploads")
        .select("*")
        .eq("user_id", user["id"])
        .eq("status", "parsed")
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    row = (res.data or [None])[0]
    if not row:
        nt.log("schedule_apply: nothing parsed to apply")
        raise SystemExit(0)

    parsed = row.get("parsed_json") or {}
    stats = upsert_classes_from_parsed(user["id"], parsed)

    # Mark applied
    sb.table("schedule_uploads").update({
        "status": "applied"
    }).eq("id", row["id"]).execute()

    nt.send(f"✅ تم إضافة/تحديث الجدول.\nجديد: {stats['inserted']} | تم تخطي: {stats['skipped']}")
    db.log_event("schedule_apply", "success", message=str(stats), user_id=user["id"])
