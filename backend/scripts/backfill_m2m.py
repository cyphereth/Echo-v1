"""Backfill intel_mention_directions for mentions that have no m2m rows.

The realtime listener historically stored mentions WITHOUT writing the
m2m direction tags that power Feed v2 (only the poller did). Those posts
never show up in the v2 columns. This one-shot script tags every mention
that has zero m2m rows, using the same _write_m2m_for_mention logic.

Run:  cd backend && python3 scripts/backfill_m2m.py [--days N]   (default 7)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.core.db import init_db, get_session  # noqa: E402
from radar.intel.models import IntelMention, IntelMentionDirection  # noqa: E402
from radar.intel.collector import _write_m2m_for_mention  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="how far back to backfill")
    args = ap.parse_args()

    init_db()
    session = get_session()
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).replace(tzinfo=None)
        tagged_ids = session.query(IntelMentionDirection.mention_id).distinct()
        rows = (session.query(IntelMention)
                .filter(IntelMention.created_at >= since,
                        ~IntelMention.id.in_(tagged_ids))
                .order_by(IntelMention.id)
                .all())
        print(f"mentions without m2m rows in last {args.days}d: {len(rows)}")
        done = 0
        for m in rows:
            _write_m2m_for_mention(session, m)
            done += 1
            if done % 500 == 0:
                session.commit()
                print(f"  …{done}")
        session.commit()
        print(f"backfilled {done} mentions")
    finally:
        session.close()


if __name__ == "__main__":
    main()
