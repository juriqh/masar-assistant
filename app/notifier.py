# app/notifier.py
from __future__ import annotations
import os, json, requests
from typing import Optional, Dict, Any

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
WEBHOOK_LOG = os.getenv("DISCORD_WEBHOOK_LOG_URL")

def _post(url: str, payload: Dict[str, Any]) -> bool:
    if DRY_RUN:
        print("[DRY_RUN] Discord payload:", json.dumps(payload, ensure_ascii=False))
        return True
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.status_code in (200, 204)
    except Exception as e:
        print("Discord error:", e)
        return False

def send(content: str, embed: Optional[Dict[str, Any]] = None) -> bool:
    if not WEBHOOK:
        print("No DISCORD_WEBHOOK_URL set.")
        return False
    payload = {"content": content}
    if embed:
        payload["embeds"] = [embed]
    return _post(WEBHOOK, payload)

def log(content: str, embed: Optional[Dict[str, Any]] = None) -> bool:
    url = WEBHOOK_LOG or WEBHOOK
    if not url:
        print("No log webhook configured.")
        return False
    payload = {"content": content}
    if embed:
        payload["embeds"] = [embed]
    return _post(url, payload)
