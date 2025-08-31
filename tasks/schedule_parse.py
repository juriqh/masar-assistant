# tasks/schedule_parse.py
import os, json
from app import notifier as nt
from app import db
from app.ocr import download_bytes, gemini_extract_schedule

ACTIVE = (os.getenv("ACTIVE_USER", "fatoom") or "fatoom").strip()

def _get_user():
    return db.get_user_by_handle(ACTIVE)

if __name__ == "__main__":
    user = _get_user()
    if not user:
        nt.log("schedule_parse: no user")
        raise SystemExit(0)

    sb = db._client(service=True)  # type: ignore
    res = (
        sb.table("schedule_uploads")
        .select("*")
        .eq("user_id", user["id"])
        .eq("status", "new")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    row = (res.data or [None])[0]
    if not row:
        nt.log("schedule_parse: no new uploads")
        raise SystemExit(0)

    file_path = row["file_path"]
    bts, mime = download_bytes(file_path)
    out = gemini_extract_schedule(bts, mime)
    parsed = out.get("json")
    text = out.get("text") or ""

    sb.table("schedule_uploads").update({
        "ocr_text": text[:10000],  # keep it reasonable
        "parsed_json": parsed or {},
        "status": "parsed" if parsed else "error",
    }).eq("id", row["id"]).execute()

    if parsed:
        # small preview
        classes = (parsed or {}).get("classes") or []
        preview = "\n".join([f"- {c.get('class_code','?')} {c.get('start_time','??:??')}–{c.get('end_time','??:??')} {c.get('days_of_week',[])}" for c in classes[:6]])
        nt.log(f"schedule_parse: parsed {len(classes)} classes\n{preview}")
        nt.send("📅 تم استخراج الجدول مبدئيًا. راجعي القائمة في الداشبورد قريبًا.")
        db.log_event("schedule_parse", "success", message=f"parsed={len(classes)}", user_id=user["id"])
    else:
        nt.log("schedule_parse: parsing failed")
        db.log_event("schedule_parse", "fail", message="no json", user_id=user["id"])
