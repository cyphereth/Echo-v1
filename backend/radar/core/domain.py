from __future__ import annotations
from dataclasses import dataclass
from typing import Type


@dataclass(frozen=True)
class DomainModels:
    """Bundle of a domain's ORM classes + its owner FK column name, so the
    generic clustering engine can read/write the right tables without Scope."""
    owner_field: str            # "brand_id" or "topic_id"
    Mention: Type
    Incident: Type
    Story: Type
    StoryPoint: Type

    def owner_kwargs(self, owner_id: int) -> dict:
        return {self.owner_field: owner_id}
