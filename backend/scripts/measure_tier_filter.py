"""Разовый замер: сколько постов из БД прошло бы новое tier-правило.

Запуск: cd backend && python scripts/measure_tier_filter.py
Печатает: всего постов, прошло (admit), отсеяно (drop), доля отсева.
НИЧЕГО не меняет в БД — только читает.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from radar.core.db import get_session
from radar.intel.collector import load_lexicon_tiers, keyword_relevant, _geo_hit


def main():
    with get_session() as s:
        tiers = load_lexicon_tiers(s)
        rows = s.execute(
            text("select text from intel_mentions where text is not null")
        ).fetchall()
    total = len(rows)
    admit = sum(1 for (t,) in rows if keyword_relevant(t, tiers, geo_hit=_geo_hit(t)))
    drop = total - admit
    print(f"total={total}  admit={admit}  drop={drop}  drop%={100*drop/max(total,1):.1f}")


if __name__ == "__main__":
    main()
