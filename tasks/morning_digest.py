import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from app import orchestrator

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    p.add_argument("--asof", type=str, help="YYYY-MM-DD HH:MM in Asia/Riyadh")  # optional test override
    args = p.parse_args()

    asof_dt = None
    if args.asof:
        asof_dt = datetime.strptime(args.asof, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Riyadh"))

    orchestrator.morning_digest(force=args.force, asof=asof_dt)
