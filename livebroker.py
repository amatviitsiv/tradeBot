import math
import logging
from binance import AsyncClient

log = logging.getLogger(__name__)

class LiveBroker:
    def __init__(self, client: AsyncClient):
        self.client = client
        self.exchange_info = None

    async def init(self):
        self.exchange_info = await self.client.get_exchange_info()

    def _get_symbol_info(self, symbol):
        for s in self.exchange_info["symbols"]:
            if s["symbol"] == symbol:
                return s
        raise ValueError(f"Symbol {symbol} not found in exchange info")

    def _adjust_qty(self, symbol, qty):
        s_info = self._get_symbol_info(symbol)
        for f in s_info["filters"]:
            if f["filterType"] == "LOT_SIZE":
                step = float(f["stepSize"])
                qty = math.floor(qty / step) * step
            if f["filterType"] == "MIN_NOTIONAL":
                min_notional = float(f["minNotional"])
        return qty, min_notional

    async def create_market_order(self, symbol, side, qty, price=None):
        qty, min_notional = self._adjust_qty(symbol, qty)
        notional = qty * (price or 0)
        if notional < min_notional:
            log.warning(f"[BROKER] {symbol} notional {notional:.2f} < min {min_notional}, adjusting qty")
            qty = min_notional / (price or 1)
        try:
            order = await self.client.create_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=qty
            )
            log.info(f"[LIVE] {side} {symbol} {qty} (status={order['status']})")
            return order
        except Exception as e:
            log.error(f"[LIVE ERROR] {symbol} {side}: {e}")
            return None
