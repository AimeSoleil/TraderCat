import aiohttp
from trade_bot.notification.base import Notifier

# Replace with your actual Discord webhook URL
DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/YOUR_WEBHOOK_URL'

class DiscordNotifier(Notifier):
    def __init__(self, webhook_url: str = DISCORD_WEBHOOK_URL):
        self.webhook_url = webhook_url

    async def send(self, message: str):
        async with aiohttp.ClientSession() as session:
            await session.post(
                self.webhook_url,
                json={"content": message}
            )