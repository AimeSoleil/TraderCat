"""AI Roles module — Identity, MacroAnalyst, OptionsStrategist, Summarizer."""
from tradercat.ai.roles.base import AIRole, RoleType
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.roles.macro_analyst import MacroAnalystRole
from tradercat.ai.roles.options_strategist import OptionsStrategistRole
from tradercat.ai.roles.summarizer import SummarizerRole

__all__ = [
    "AIRole",
    "RoleType",
    "IdentityRole",
    "MacroAnalystRole",
    "OptionsStrategistRole",
    "SummarizerRole",
]
