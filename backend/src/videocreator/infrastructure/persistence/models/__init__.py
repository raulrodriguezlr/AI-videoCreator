"""ORM models — flat module so a single import registers all tables."""

from videocreator.infrastructure.persistence.models.tables import (
    CharacterRow,
    EpisodeRow,
    JobRow,
    PodRow,
    ScriptRow,
    ShortRow,
    TopicRow,
    UserRow,
)

__all__ = [
    "CharacterRow",
    "EpisodeRow",
    "JobRow",
    "PodRow",
    "ScriptRow",
    "ShortRow",
    "TopicRow",
    "UserRow",
]
