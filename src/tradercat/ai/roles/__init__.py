"""AI Roles module — Identity, Analyst, Summarizer."""
from tradercat.ai.roles.base import AIRole, RoleType
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.roles.analyst import AnalystRole
from tradercat.ai.roles.summarizer import SummarizerRole

__all__ = [
    "AIRole",
    "RoleType",
    "IdentityRole",
    "AnalystRole",
    "SummarizerRole",
]
