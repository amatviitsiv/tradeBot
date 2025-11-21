import aiohttp, asyncio, logging
import config as cfg
log = logging.getLogger(__name__)
class TelegramNotifier:
    def __init__(self, token: str, chat_id: int):
        self.token = token
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.session = None
        self._lock = asyncio.Lock()
    async def _ensure(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
    async def send(self, text: str):
        await self._ensure()
        payload = {"chat_id": self.chat_id, "text": text}
        try:
            async with self._lock:
                async with self.session.post(self.url, json=payload, timeout=10) as resp:
                    if resp.status != 200:
                        data = await resp.text()
                        log.warning(f"[TELEGRAM] non-200 {resp.status}: {data}")
        except Exception as e:
            log.exception(f"[TELEGRAM] send failed: {e}")
    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None
