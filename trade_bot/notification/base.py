from abc import ABC, abstractmethod
import asyncio

class Notifier(ABC):
    @abstractmethod
    async def send(self, message: str):
        pass
