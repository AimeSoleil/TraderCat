import os
import aiohttp
from tradercat.logger.logger import get_logger
from tradercat.notification.base import Notifier

logger = get_logger(__name__)
# 从环境变量读取 Discord Webhook URL
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

class DiscordNotifier(Notifier):
    def __init__(self, webhook_url: str = DISCORD_WEBHOOK_URL):
        self.webhook_url = webhook_url

    async def send(self, message: str):
        if not self.webhook_url or len(self.webhook_url) <= 0:
            logger.info("Discord webhook URL not set. Skipping notification.")
            return
        
        async with aiohttp.ClientSession() as session:
            await session.post(
                self.webhook_url,
                json={"content": message}
            )