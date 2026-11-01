"""Reset the demo to a clean state: cases, evidence, portal claims, and (with --logs) the event and usage logs.

    python scripts/reset.py [--logs]

If the orchestrator is running it is asked to reset itself (which also resets the portal). Otherwise the database is reseeded directly.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ghante_shared import config, db, http  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs", action="store_true", help="also empty logs/events.jsonl and logs/usage.json")
    args = ap.parse_args()
    config.ensure_dirs()
    try:
        out = http.post_json(f"{config.ORCH_URL}/api/scenario/reset", {}, timeout=10)
        print("orchestrator reset:", out)
    except Exception as e:
        print(f"orchestrator not running ({type(e).__name__}); reseeding the database directly")
        conn = db.connect()
        print("database:", db.load_seed(conn))
        conn.close()
        shutil.rmtree(config.EVIDENCE_DIR, ignore_errors=True)
        try:
            print("portal reset:", http.post_json(f"{config.PORTAL_URL}/api/reset", {}, timeout=5))
        except Exception:
            if config.PORTAL_DB_PATH.exists():
                config.PORTAL_DB_PATH.unlink()
            print("portal not running; its database file was removed")
    if args.logs:
        for f in (config.EVENTS_LOG, config.USAGE_LOG):
            if f.exists():
                f.write_text("" if f.suffix == ".jsonl" else "{}", encoding="utf-8")
        print("logs emptied")
    config.ensure_dirs()
    return 0


if __name__ == "__main__":
    sys.exit(main())
