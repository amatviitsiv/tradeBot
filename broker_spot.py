# broker_spot.py
import logging, time
from typing import Dict, Optional
from asyncio import sleep as async_sleep
from binance import AsyncClient
import config as cfg
from utils import split_symbol, round_down

logger = logging.getLogger(__name__)
trades_logger = logging.getLogger("trades")
errors_logger = logging.getLogger("errors")

class PaperSpotBroker:
    def __init__(self, starting_balance_usdt: float = cfg.INITIAL_BALANCE_USDT):
        self.balances: Dict[str, float] = {"USDT": float(starting_balance_usdt)}
        self.history = []

    def get_balance(self, asset: str) -> float:
        return float(self.balances.get(asset, 0.0))

    def get_balances(self) -> Dict[str, float]:
        return dict(self.balances)

    def get_equity(self, market_prices: Dict[str, float]) -> float:
        # IMPORTANT: this method must exist — manager.py calls it in paper mode
        eq = 0.0
        for asset, amt in self.balances.items():
            if amt == 0:
                continue
            if asset == "USDT":
                eq += amt
            else:
                sym = asset + "USDT"
                px = market_prices.get(sym)
                if px is not None:
                    eq += amt * px
                else:
                    logger.debug(f"[PAPER-SPOT] no price for {asset} ({sym}), skipping")
        logger.info(f"[EQUITY] {eq:.2f} USDT")
        return eq

    def _record(self, rec: Dict):
        for k, v in list(rec.items()):
            if hasattr(v, "item"):
                try:
                    rec[k] = float(v)
                except Exception:
                    pass
        rec["ts"] = time.time()
        self.history.append(rec)
        trades_logger.info(rec)

    def create_market_order(self, symbol: str, side: str, qty: float, price: float) -> Optional[Dict]:
        side = side.upper()
        base, quote = split_symbol(symbol)
        if base is None or quote is None:
            errors_logger.error(f"[PAPER-SPOT] bad symbol {symbol}")
            return None

        qty = float(qty)
        price = float(price)
        notional = qty * price

        if not cfg.USE_BNB_FEES:
            fee = notional * cfg.PAPER_TAKER_FEE
        else:
            fee = notional * cfg.PAPER_TAKER_FEE

        if side == "BUY":
            total_cost = notional + fee
            available = self.get_balance(quote)
            if available + 1e-9 < total_cost:
                logger.warning(f"[PAPER-SPOT] insufficient {quote} ({available} < {total_cost})")
                return None
            self.balances[quote] = round(float(self.balances.get(quote, 0.0)) - total_cost, 12)
            self.balances[base] = round(float(self.balances.get(base, 0.0)) + qty, 12)
            rec = {"side": "BUY", "symbol": symbol, "qty": float(qty), "price": float(price), "notional": float(notional), "fee": float(fee)}
            self._record(rec)
            logger.info(f"[PAPER-SPOT] BUY {symbol} {qty:.8f} @ {price:.2f} cost={total_cost:.2f} fee={fee:.6f}")
            return rec

        elif side == "SELL":
            pos_qty = self.get_balance(base)
            if pos_qty + 1e-9 < qty:
                logger.warning(f"[PAPER-SPOT] insufficient {base} to SELL ({pos_qty} < {qty})")
                return None
            proceeds = qty * price
            fee = proceeds * cfg.PAPER_TAKER_FEE
            net = proceeds - fee
            self.balances[base] = round(float(self.balances.get(base, 0.0)) - qty, 12)
            self.balances[quote] = round(float(self.balances.get(quote, 0.0)) + net, 12)
            rec = {"side": "SELL", "symbol": symbol, "qty": float(qty), "price": float(price), "proceeds": float(proceeds), "fee": float(fee), "net": float(net)}
            self._record(rec)
            logger.info(f"[PAPER-SPOT] SELL {symbol} {qty:.8f} @ {price:.2f} net={net:.2f} fee={fee:.6f}")
            return rec
        else:
            raise ValueError("side must be BUY or SELL")

    def get_pnl(self, symbol: str, last_price: float) -> Optional[Dict]:
        base, quote = split_symbol(symbol)
        if base is None:
            return None
        qty = self.get_balance(base)
        if qty <= 0:
            return None
        buys = [h for h in self.history if h.get("symbol") == symbol and h.get("side") == "BUY"]
        if not buys:
            return None
        total_qty = sum(float(b["qty"]) for b in buys)
        if total_qty == 0:
            return None
        total_cost = sum(float(b["qty"]) * float(b["price"]) + float(b.get("fee", 0.0)) for b in buys)
        avg_entry = total_cost / total_qty
        pnl_usdt = (float(last_price) - avg_entry) * qty
        pnl_pct = (float(last_price) / avg_entry - 1) * 100.0
        return {"usdt": pnl_usdt, "pct": pnl_pct}


class LiveSpotBroker:
    def __init__(self, client: AsyncClient):
        self.client = client
        self._symbol_info = {}
        self._exchange_info = None
        self._balances = {}

    async def init(self):
        if self._exchange_info is None:
            self._exchange_info = await self.client.get_exchange_info()
            for s in self._exchange_info.get("symbols", []):
                info = {"stepSize": None, "tickSize": None, "minQty": None, "minNotional": None, "baseAsset": s.get("baseAsset"), "quoteAsset": s.get("quoteAsset")}
                for f in s.get("filters", []):
                    if f.get("filterType") == "LOT_SIZE":
                        info["stepSize"] = float(f.get("stepSize", "0"))
                        info["minQty"] = float(f.get("minQty", "0"))
                    if f.get("filterType") == "PRICE_FILTER":
                        info["tickSize"] = float(f.get("tickSize", "0"))
                    if f.get("filterType") == "MIN_NOTIONAL":
                        info["minNotional"] = float(f.get("minNotional", "0"))
                self._symbol_info[s["symbol"]] = info
        await self.update_balances()

    async def update_balances(self):
        acct = await self.client.get_account()
        self._balances = {b["asset"]: float(b["free"]) for b in acct.get("balances", []) if float(b.get("free", 0.0)) > 0.0}
        return self._balances

    def get_balance(self, asset: str) -> float:
        return float(self._balances.get(asset, 0.0))

    def _round_qty(self, symbol: str, qty: float) -> float:
        info = self._symbol_info.get(symbol, {})
        step = info.get("stepSize")
        if step:
            return round_down(qty, step)
        return qty

    async def create_market_order(self, symbol: str, side: str, qty: float, price: float = None) -> Optional[Dict]:
        if not self._symbol_info:
            await self.init()
        info = self._symbol_info.get(symbol)
        if not info:
            raise ValueError(f"No symbol info for {symbol}")

        if price is None:
            ticker = await self.client.get_symbol_ticker(symbol=symbol)
            price = float(ticker.get("price"))

        qty = float(qty)
        qty = self._round_qty(symbol, qty)
        if qty <= 0:
            raise ValueError("Rounded qty <= 0")

        min_qty = info.get("minQty") or 0.0
        if min_qty and qty < min_qty:
            adj = self._round_qty(symbol, min_qty * 1.01)
            logger.warning(f"[LIVE-SPOT] {symbol} qty {qty} < minQty {min_qty}, adjusted -> {adj}")
            qty = adj

        min_notional = info.get("minNotional") or 0.0
        notional = qty * price
        if min_notional and notional < min_notional:
            min_qty_for_not = (min_notional / price) * 1.01
            adj = self._round_qty(symbol, max(qty, min_qty_for_not))
            logger.warning(f"[LIVE-SPOT] {symbol} notional {notional:.2f} < minNotional {min_notional}, adjusted qty -> {adj}")
            qty = adj

        base = info.get("baseAsset")
        if side.upper() == "SELL":
            bal = self.get_balance(base)
            if bal < qty:
                logger.error(f"[LIVE-SPOT] Not enough {base} to SELL ({bal} < {qty})")
                return None

        last_exc = None
        for attempt in range(cfg.ORDER_RETRY):
            try:
                res = await self.client.create_order(symbol=symbol, side=side.upper(), type="MARKET", quantity=qty)
                await async_sleep(0.2)
                await self.update_balances()
                logger.info(f"[LIVE-SPOT] {side.upper()} {symbol} qty={qty:.8f}")
                trades_logger.info({"side": side.upper(), "symbol": symbol, "qty": qty, "price": price})
                return res
            except Exception as e:
                last_exc = e
                errors_logger.warning(f"[LIVE-SPOT] order attempt {attempt+1} failed: {e}")
                await async_sleep(cfg.ORDER_RETRY_DELAY)
        raise last_exc
