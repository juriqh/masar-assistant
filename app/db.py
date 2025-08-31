def get_classes_for_day(user_id: str, day_token: str) -> List[Dict[str, Any]]:
    """
    Returns today's classes even if `days_of_week` is stored as text or text[].
    Accepts tokens like 'Sun','Mon','Tue','Wed','Thu','Fri','Sat'.
    """
    sb = _client(service=True)
    if not sb:
        return []
    res = (
        sb.table("classes")
        .select("*")
        .eq("user_id", user_id)
        .eq("active", True)
        .order("start_time")
        .execute()
    )
    rows = res.data or []
    out: List[Dict[str, Any]] = []
    for c in rows:
        days = c.get("days_of_week")
        if isinstance(days, list):
            # Proper text[] column
            if day_token in days:
                out.append(c)
        elif isinstance(days, str):
            # Stored as text like "{Sun,Tue,Thu}" or "Sun,Tue,Thu"
            raw = days.strip().strip("{}")
            tokens = [t.strip() for t in raw.split(",") if t.strip()]
            if day_token in tokens:
                out.append(c)
        else:
            # Unknown format → skip
            continue
    return out
