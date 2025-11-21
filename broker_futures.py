import logging, time
from typing import Dict, Optional
from asyncio import sleep as async_sleep
from binance import AsyncClient
import config as cfg
from utils import split_symbol

logger = logging.getLogger(__name__)
trades_logger = logging.getLogger("trades")
errors_logger = logging.getLogger("errors")

class PaperFuturesBroker:
    def __init__(self, starting_balance_usdt: float = cfg.INITIAL_BALANCE_USDT, leverage: int = 3):
        self.balance = float(starting_balance_usdt)
        self.positions: Dict[str, Dict] = {}  # symbol -> {side, qty, entry, notional, unrealized}
        self.leverage = leverage
        self.history = []

    def get_balance(self):
        return float(self.balance)

    def _record(self, rec: Dict):
        rec['ts'] = time.time()
        self.history.append(rec)
        trades_logger.info(rec)

    def open_position(self, symbol: str, side: str, qty: float, price: float):
        side = side.upper()
        notional = qty * price
        margin = notional / self.leverage
        fee = notional * cfg.PAPER_TAKER_FEE
        if self.balance + 1e-9 < margin + fee:
            logger.warning(f"[PAPER-FUT] insufficient balance to open {symbol} {side} notional={notional:.2f} margin={margin:.2f} fee={fee:.4f}")
            return None
        self.balance -= (margin + fee)
        self.positions[symbol] = {"side": side, "qty": qty, "entry": price, "notional": notional, "leverage": self.leverage}
        rec = {"side": side, "symbol": symbol, "qty": qty, "price": price, "notional": notional, "fee": fee, "action": "open"}
        self._record(rec)
        logger.info(f"[PAPER-FUT] OPEN {symbol} {side} qty={qty:.6f} @ {price:.2f} margin={margin:.2f} fee={fee:.4f}")
        return rec

    def close_position(self, symbol: str, price: float):
        pos = self.positions.get(symbol)
        if not pos:
            logger.warning(f"[PAPER-FUT] no pos to close for {symbol}")
            return None
        side = pos['side']
        qty = pos['qty']
        entry = pos['entry']
        notional = pos['notional']
        # PnL: for SHORT, profit = (entry - close) * qty; for LONG, profit = (close - entry) * qty
        if side == 'SELL':
            pnl = (entry - price) * qty
        else:
            pnl = (price - entry) * qty
        fee = notional * cfg.PAPER_TAKER_FEE
        self.balance += (notional / pos['leverage']) + pnl - fee
        rec = {"side": side, "symbol": symbol, "qty": qty, "price": price, "pnl": pnl, "fee": fee, "action": "close"}
        self._record(rec)
        del self.positions[symbol]
        logger.info(f"[PAPER-FUT] CLOSE {symbol} {side} qty={qty:.6f} @ {price:.2f} pnl={pnl:.2f} fee={fee:.4f} balance={self.balance:.2f}")
        return rec

    def get_pnl(self, symbol: str, mark_price: float):
        pos = self.positions.get(symbol)
        if not pos:
            return None
        side = pos['side']
        qty = pos['qty']
        entry = pos['entry']
        if side == 'SELL':
            pnl = (entry - mark_price) * qty
        else:
            pnl = (mark_price - entry) * qty
        pct = pnl / pos['notional'] * 100 if pos.get('notional') else 0.0
        return {"usdt": pnl, "pct": pct}

class LiveFuturesBroker:
    def __init__(self, client: AsyncClient):
        self.client = client

    async def init(self):
        return

    async def update_balance(self):
        acct = await self.client.futures_account()
        bal = {}
        if "assets" in acct:
            for a in acct["assets"]:
                asset = a.get("asset")
                free = float(a.get("availableBalance", 0.0))
                bal[asset] = free
        if not bal:
            bal["USDT"] = float(acct.get("totalWalletBalance", 0.0))
        return bal

    async def set_leverage(self, symbol: str, leverage: int):
        try:
            await self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"[FUTURES] set leverage {symbol} -> {leverage}")
        except Exception as e:
            errors_logger.warning(f"[FUTURES] leverage set failed for {symbol}: {e}")

    async def create_market_order(self, symbol: str, side: str, qty: float, price: float = None, reduce_only: bool = False):
        if price is None:
            tick = await self.client.futures_symbol_ticker(symbol=symbol)
            price = float(tick.get("price"))
        params = {"symbol": symbol, "side": side.upper(), "type": "MARKET", "quantity": float(qty)}
        if reduce_only:
            params["reduceOnly"] = True
        last_exc = None
        for attempt in range(cfg.ORDER_RETRY):
            try:
                res = await self.client.futures_create_order(**params)
                await async_sleep(0.2)
                logger.info(f"[FUTURES] {side} {symbol} qty={qty}")
                trades_logger.info({"side": side.upper(), "symbol": symbol, "qty": qty, "price": price, "reduceOnly": reduce_only})
                return res
            except Exception as e:
                last_exc = e
                errors_logger.warning(f"[FUTURES] order attempt {attempt+1} failed: {e}")
                await async_sleep(cfg.ORDER_RETRY_DELAY)
        errors_logger.exception(f"[FUTURES] failed create market order: {last_exc}")
        return None
