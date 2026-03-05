"""Identity prompt registry for all available analysis identities."""
from typing import Dict

# Registry mapping identity key → module
IDENTITY_REGISTRY: Dict[str, str] = {
    "options_strategist": "tradercat.ai.prompts.identities.options_strategist",
    "summarizer": "tradercat.ai.prompts.identities.summarizer",
}
