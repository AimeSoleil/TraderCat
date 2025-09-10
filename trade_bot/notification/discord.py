import aiohttp
from trade_bot.notification.base import Notifier

DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/1412999975872368843/VOv5UsUszt6BzzyeK62dFDhlX25CHH3f4rCTYzoREzFI125WqGq_t0XxAhDUsu0YCKHa'

class DiscordNotifier(Notifier):
    def __init__(self, webhook_url: str = DISCORD_WEBHOOK_URL):
        self.webhook_url = webhook_url

    async def send(self, message: str):
        async with aiohttp.ClientSession() as session:
            await session.post(
                self.webhook_url,
                json={"content": message}
            )