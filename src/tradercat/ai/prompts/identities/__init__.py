"""Identity prompt registry for all available analysis identities."""
from typing import Dict

# Registry mapping identity key → module
IDENTITY_REGISTRY: Dict[str, str] = {
    "wyckoff": "tradercat.ai.prompts.identities.wyckoff",
    "options_strategist": "tradercat.ai.prompts.identities.options_strategist",
}
