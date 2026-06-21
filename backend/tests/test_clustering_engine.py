import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def _setup():
    from sqlalchemy import create_engine, Integer, Text, Float, Boolean, ForeignKey
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

    class Base(DeclarativeBase):
        pass

    class M(Base):
        __tablename__ = "m"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        topic_id: Mapped[int] = mapped_column(Integer)
        text: Mapped[str] = mapped_column(Text, default="")
        author: Mapped[str] = mapped_column(Text, default="")
        created_at: Mapped[datetime] = mapped_column()
        incident_id: Mapped[int] = mapped_column(ForeignKey("inc.id"), nullable=True)

    class Inc(Base):
        __tablename__ = "inc"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        topic_id: Mapped[int] = mapped_column(Integer)
        story_id: Mapped[int] = mapped_column(ForeignKey("st.id"), nullable=True)
        title: Mapped[str] = mapped_column(Text, default="")
        post_count: Mapped[int] = mapped_column(Integer, default=1)
        first_seen_at: Mapped[datetime] = mapped_column()
        last_seen_at: Mapped[datetime] = mapped_column()

    class St(Base):
        __tablename__ = "st"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        topic_id: Mapped[int] = mapped_column(Integer)
        title: Mapped[str] = mapped_column(Text, default="")
        status: Mapped[str] = mapped_column(Text, default="active")
        is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
        post_count: Mapped[int] = mapped_column(Integer, default=0)
        first_seen_at: Mapped[datetime] = mapped_column()
        last_seen_at: Mapped[datetime] = mapped_column()

    class SP(Base):
        __tablename__ = "sp"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        story_id: Mapped[int] = mapped_column(ForeignKey("st.id"))
        bucket_start: Mapped[datetime] = mapped_column()
        mention_count: Mapped[int] = mapped_column(Integer, default=0)

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng), M, Inc, St, SP


def test_engine_clusters_similar_mentions_into_one_story():
    from radar.core.clustering import cluster_owner
    from radar.core.domain import DomainModels
    s, M, Inc, St, SP = _setup()
    now = datetime.now(timezone.utc)
    s.add_all([
        M(topic_id=1, text="взрыв на нефтебазе под Брянском", author="a", created_at=now),
        M(topic_id=1, text="взрыв нефтебаза Брянск область", author="b", created_at=now),
    ])
    s.commit()
    models = DomainModels(owner_field="topic_id", Mention=M, Incident=Inc, Story=St, StoryPoint=SP)
    cluster_owner(s, owner_id=1, models=models, embed=lambda txt: [float(len(txt))])
    assert s.query(St).count() >= 1
    assert all(m.incident_id is not None for m in s.query(M).all())
