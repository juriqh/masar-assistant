# app/embeddings_rag.py
from __future__ import annotations
import os
from typing import List, Dict, Any, Optional
from datetime import date
from . import db

# MVP: we won't actually compute embeddings yet. We'll just fetch recent notes.

def search_recent_notes(user_id: str, class_id: str, limit: int = 3) -> List[Dict[str, Any]]:
    # You could extend this later to true vector search.
    sb_notes = db.get_notes_for_day(user_id, date.today())  # notes today
    # Filter by class_id then fall back to latest note if none today
    filtered = [n for n in sb_notes if n.get("class_id") == class_id]
    if filtered:
        return filtered[:limit]
    # No notes today → fetch latest one overall
    last = db.get_latest_note_for_class(user_id, class_id)
    return [last] if last else []
