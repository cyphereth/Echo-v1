from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Scope:
    """Owner of a collection/analytics pass — either a Brand or a Topic.

    Carries the keywords used to query/relevance-gate, and produces the right
    owner FK kwargs so the same pipeline writes brand_id OR topic_id.
    """
    kind: str            # 'brand' | 'topic'
    id: int
    name: str
    keywords: list[str] = field(default_factory=list)
    niche_keywords: list[str] = field(default_factory=list)
    market: str = "ru"
    local_mode: bool = False

    def owner_kwargs(self) -> dict:
        return {f"{self.kind}_id": self.id}


def scope_for_brand(b) -> Scope:
    return Scope("brand", b.id, b.name, b.keywords_list(), b.niche_keywords_list(),
                 getattr(b, "market", "ru"), getattr(b, "local_mode", False))


def scope_for_topic(t) -> Scope:
    return Scope("topic", t.id, t.name, t.keywords_list(), t.niche_keywords_list(),
                 getattr(t, "market", "ru"), False)
