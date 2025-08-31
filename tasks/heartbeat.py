# tasks/heartbeat.py
import os
from datetime import datetime
from app import notifier as nt
from app import db

if __name__ == "__main__":
    msg = f"🫀 Masar heartbeat @ {datetime.utcnow().isoformat()}Z (DRY_RUN={os.getenv('DRY_RUN','true')})"
    nt.log(msg)
    db.log_event("heartbeat", "success", message="alive")
