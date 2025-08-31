import os
# app/orchestrator.py (top env section)
ACTIVE_USER = (os.getenv("ACTIVE_USER", "fatoom") or "fatoom").strip()
# ... keep the rest

def _get_user():
    u = db.get_user_by_handle(ACTIVE_USER)
    if not u:
        # Helpful debug log showing what handles exist
        try:
            handles = db.debug_user_handles()
        except Exception:
            handles = []
        nt.log(f"morning_digest: no user for handle='{ACTIVE_USER}'. Known handles: {handles}")
    return u
