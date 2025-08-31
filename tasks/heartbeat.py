# tasks/heartbeat.py
import os
from datetime import datetime
from app import notifier as nt
from app import db

if __name__ == "__main__":
    active = (os.getenv("ACTIVE_USER", "fatoom") or "fatoom").strip()
    handles = db.debug_user_handles()
    msg = (
        f"🫀 Masar heartbeat @ {datetime.utcnow().isoformat()}Z "
        f"(DRY_RUN={os.getenv('DRY_RUN','true')})\n"
        f"ACTIVE_USER='{active}' | known handles={handles}"
    )
    nt.log(msg)
    db.log_event("heartbeat", "success", message=f"active={active}")
