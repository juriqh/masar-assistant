# tasks/morning_digest.py
import argparse, inspect, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from app import orchestrator

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    p.add_argument("--asof", type=str, help="YYYY-MM-DD HH:MM in Asia/Riyadh")
    args = p.parse_args()

    asof_dt = None
    if args.asof:
        asof_dt = datetime.strptime(args.asof, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Riyadh"))

    sig = inspect.signature(orchestrator.morning_digest)
    params = sig.parameters

    try:
        # Call with whatever the function actually supports.
        if "force" in params and "asof" in params:
            orchestrator.morning_digest(force=args.force, asof=asof_dt)
        elif "asof" in params:
            orchestrator.morning_digest(asof=asof_dt)
        elif "force" in params:
            orchestrator.morning_digest(force=args.force)
        else:
            orchestrator.morning_digest()
    except TypeError as e:
        print(f"[morning_digest] TypeError: {e}", file=sys.stderr)
        print(f"Function signature is: {sig}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()
