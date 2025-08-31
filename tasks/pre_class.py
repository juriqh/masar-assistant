# tasks/pre_class.py
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from app import orchestrator

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--asof", type=str, help='YYYY-MM-DD HH:MM (Asia/Riyadh)')
    args = p.parse_args()

    asof_dt = None
    if args.asof:
        asof_dt = datetime.strptime(args.asof, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Riyadh"))

    orchestrator.pre_class_reminder(asof=asof_dt)

if __name__ == "__main__":
    main()
