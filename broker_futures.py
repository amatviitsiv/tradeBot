import logging, time
from typing import Dict, Optional
from asyncio import sleep as async_sleep
import config as cfg

logger = logging.getLogger(__name__)
trades_logger = logging.getLogger("trades")
errors_logger = logging.getLogger("errors")

class LiveFuturesBroker:
    def __init__(self, client):
        self.client = client
        self._symbol_info = {}
        self._exchange_info = None
        self._balance = {}
        self._leverage = {}

    async def init(self):
        try:
            self._exchange_info = await self.client.futures_exchange_info()
            for s in self._exchange_info.get("symbols", []):
                self._symbol_info[s["symbol"]] = s
        except Exception:
            pass
        await self.update_balance()

    async def update_balance(self):
        try:
            acct = await self.client.futures_account()
        except Exception:
            acct = {}
        bal = {}
        if "assets" in acct:
            for a in acct["assets"]:
                asset = a.get("asset")
                free = float(a.get("availableBalance", 0.0))
                bal[asset] = free
        if not bal:
            bal["USDT"] = float(acct.get("totalWalletBalance", cfg.INITIAL_BALANCE_USDT))
        self._balance = bal
        return self._balance

    def get_balance(self, asset: str) -> float:
        return float(self._balance.get(asset, 0.0))

    async def set_leverage(self, symbol: str, leverage: int):
        leverage = min(leverage, cfg.FUTURES_MAX_LEVERAGE)
        try:
            await self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            self._leverage[symbol] = leverage
            logger.info(f"[FUTURES] set leverage {symbol} -> {leverage}")
        except Exception as e:
            errors_logger.warning(f"[FUTURES] leverage set failed for {symbol}: {e}")

    async def create_market_order(self, symbol: str, side: str, qty: float, price: float = None, reduce_only: bool = False):
        # paper/live compatible interface; in paper mode manager uses simulation
        try:
            if price is None:
                tick = await self.client.futures_symbol_ticker(symbol=symbol)
                price = float(tick.get("price"))
        except Exception:
            price = price or 0.0
        side = side.upper()
        params = {"symbol": symbol, "side": side, "type": "MARKET"}
        params["quantity"] = float(qty)
        if reduce_only:
            params["reduceOnly"] = True
        last_exc = None
        for attempt in range(cfg.ORDER_RETRY):
            try:
                res = await self.client.futures_create_order(**params)
                await async_sleep(0.2)
                await self.update_balance()
                logger.info(f"[FUTURES] {side} {symbol} qty={qty}")
                trades_logger.info({"side": side, "symbol": symbol, "qty": qty, "price": price, "reduceOnly": reduce_only})
                return res
            except Exception as e:
                last_exc = e
                errors_logger.warning(f"[FUTURES] order attempt {attempt+1} failed: {e}")
                await async_sleep(cfg.ORDER_RETRY_DELAY)
        errors_logger.exception(f"[FUTURES] failed create market order: {last_exc}")
        return None
