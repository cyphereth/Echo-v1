"""One-shot, idempotent migration: copy rows from the legacy shared tables
into the per-domain tables, routed by owner. Guarded so it only runs when the
old tables exist and the new ones are still empty. PKs and internal FKs are
preserved (an owner's whole subtree routes to one domain)."""
from __future__ import annotations
import logging
from sqlalchemy import inspect, text

log = logging.getLogger("radar.migrate")

# old table -> (news table, brand table)
# columns to copy are intersected with the destination table's columns.
_PLAN = [
    ("probes",       "news_probes",       "brand_probes"),
    ("incidents",    "news_incidents",    "brand_incidents"),
    ("stories",      "news_stories",      "brand_stories"),
    ("mentions",     "news_mentions",     "brand_mentions"),
    ("reports",      "news_reports",      "brand_reports"),
]

# Brand child tables: (old_table, new_brand_table, route_where)
# Route only rows attached to a brand-owned mention.
_BRAND_WHERE = "mention_id IN (SELECT id FROM mentions WHERE brand_id IS NOT NULL)"
_BRAND_CHILD_PLAN = [
    ("mention_snapshots", "brand_mention_snapshots", _BRAND_WHERE),
    ("comments",          "brand_comments",          _BRAND_WHERE),
    ("draft_edits",       "brand_draft_edits",       _BRAND_WHERE),
    ("engagement_log",    "brand_engagement_log",    _BRAND_WHERE),
]


def _cols(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def _copy(conn, src: str, dst: str, where: str):
    src_cols = _cols(conn, src)
    dst_cols = _cols(conn, dst)
    shared = sorted(c for c in src_cols if c in dst_cols)
    cols = ", ".join(shared)
    conn.execute(text(f"INSERT INTO {dst} ({cols}) SELECT {cols} FROM {src} WHERE {where}"))


def migrate_split(engine) -> None:
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    if "mentions" not in existing or "news_mentions" not in existing:
        return  # nothing to migrate (fresh DB built straight from new models)
    with engine.begin() as conn:
        # news_mentions and brand_mentions are the canonical sentinels: if either has rows, migration already ran.
        already = conn.execute(text("SELECT COUNT(*) FROM news_mentions")).scalar() \
            or conn.execute(text("SELECT COUNT(*) FROM brand_mentions")).scalar()
        if already:
            return
        for src, news_dst, brand_dst in _PLAN:
            if src not in existing:
                continue
            _copy(conn, src, news_dst, "topic_id IS NOT NULL")
            _copy(conn, src, brand_dst, "brand_id IS NOT NULL")
        # story_points route by their story's domain
        if "story_points" in existing:
            _copy(conn, "story_points", "news_story_points",
                  "story_id IN (SELECT id FROM stories WHERE topic_id IS NOT NULL)")
            _copy(conn, "story_points", "brand_story_points",
                  "story_id IN (SELECT id FROM stories WHERE brand_id IS NOT NULL)")
        # brand child tables: copy rows from old tables into brand-prefixed tables,
        # routed by brand-owned mention (old table names differ from brand-prefixed ones).
        for src, brand_dst, where in _BRAND_CHILD_PLAN:
            if src not in existing or brand_dst not in existing:
                continue
            _copy(conn, src, brand_dst, where)
        # verify counts for main tables
        for src, news_dst, brand_dst in _PLAN:
            if src not in existing:
                continue
            old_n = conn.execute(text(f"SELECT COUNT(*) FROM {src} WHERE topic_id IS NOT NULL")).scalar()
            old_b = conn.execute(text(f"SELECT COUNT(*) FROM {src} WHERE brand_id IS NOT NULL")).scalar()
            new_n = conn.execute(text(f"SELECT COUNT(*) FROM {news_dst}")).scalar()
            new_b = conn.execute(text(f"SELECT COUNT(*) FROM {brand_dst}")).scalar()
            if (old_n, old_b) != (new_n, new_b):
                raise RuntimeError(
                    f"migrate_split count mismatch for {src}: "
                    f"old(news={old_n},brand={old_b}) new(news={new_n},brand={new_b})")
        # verify counts for brand child tables
        for src, brand_dst, where in _BRAND_CHILD_PLAN:
            if src not in existing or brand_dst not in existing:
                continue
            old_b = conn.execute(text(f"SELECT COUNT(*) FROM {src} WHERE {where}")).scalar()
            new_b = conn.execute(text(f"SELECT COUNT(*) FROM {brand_dst}")).scalar()
            if old_b != new_b:
                raise RuntimeError(
                    f"migrate_split count mismatch for brand child {src}: "
                    f"old={old_b} new={new_b}")
        # verify counts for story_points
        if "story_points" in existing:
            old_n = conn.execute(text(
                "SELECT COUNT(*) FROM story_points WHERE story_id IN "
                "(SELECT id FROM stories WHERE topic_id IS NOT NULL)")).scalar()
            old_b = conn.execute(text(
                "SELECT COUNT(*) FROM story_points WHERE story_id IN "
                "(SELECT id FROM stories WHERE brand_id IS NOT NULL)")).scalar()
            new_n = conn.execute(text("SELECT COUNT(*) FROM news_story_points")).scalar()
            new_b = conn.execute(text("SELECT COUNT(*) FROM brand_story_points")).scalar()
            if (old_n, old_b) != (new_n, new_b):
                raise RuntimeError(
                    f"migrate_split count mismatch for story_points: "
                    f"old(news={old_n},brand={old_b}) new(news={new_n},brand={new_b})")
        log.info("migrate_split: domain tables populated from legacy tables")
