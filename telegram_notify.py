# telegram_notify.py

import aiohttp
import asyncio
import logging
import config as cfg

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Простая асинхронная отправка сообщений в Telegram.
    Работает даже в PAPER режиме.
    Не падает при ошибках (только логирует).
    """

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.session = None

    # --------------------------------------------------------------

    async def start(self):
        """Инициализация http-сессии."""
        if self.session is None:
            self.session = aiohttp.ClientSession()

    # --------------------------------------------------------------

    async def send_equity(self, equity: float):
        """
        Отдельный метод для уведомления по equity, чтобы удобно вызывать из manager.
        """
        await self.send(f"Equity: {equity:.2f} USDT")

    async def send(self, text: str):
        """Отправляет сообщение, если token/chat_id заданы."""
        if not self.token or not self.chat_id:
            return  # уведомления отключены

        if self.session is None:
            await self.start()

        payload = {
            "chat_id": self.chat_id,
            "text": text
        }

        try:
            async with self.session.post(self.api_url, json=payload, timeout=5) as resp:
                if resp.status != 200:
                    logger.warning(f"[TG] send failed: {resp.status}")
        except Exception as e:
            logger.warning(f"[TG] error: {e}")

    # --------------------------------------------------------------

    async def close(self):
        """Закрытие сессии."""
        if self.session:
            await self.session.close()
            self.session = None
