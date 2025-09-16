import os
import aiohttp
from trade_bot.notification.base import Notifier

# 从环境变量读取 Discord Webhook URL
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

class DiscordNotifier(Notifier):
    def __init__(self, webhook_url: str = DISCORD_WEBHOOK_URL):
        self.webhook_url = webhook_url

    async def send(self, message: str):
        if not self.webhook_url or len(self.webhook_url) <= 0:
            print("Discord webhook URL not set. Skipping notification.")
            return
        
        async with aiohttp.ClientSession() as session:
            await session.post(
                self.webhook_url,
                json={"content": message}
            )