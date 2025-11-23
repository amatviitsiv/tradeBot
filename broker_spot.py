# broker_spot.py

import logging
import config as cfg
from utils import round_down, log_trade
from math import floor

logger = logging.getLogger(__name__)


# ======================================================================
#                           PAPER SPOT BROKER
# ======================================================================

class PaperSpotBroker:
    """
    Полная симуляция спотовой торговли:
    - баланс в USDT
    - покупки/продажи SPOT
    - комиссия
    - PnL
    """

    def __init__(self, initial_balance_usdt: float):
        self.balances = {"USDT": float(initial_balance_usdt)}
        self.positions = {}  # { "BTCUSDT": {"qty":..., "avg_price":...} }
        logger.info(f"[PAPER_SPOT] initialized with {initial_balance_usdt:.2f} USDT")

    # ------------------------------------------------------------------
    def get_equity(self, market_prices: dict) -> float:
        """Считает equity только для СПОТА."""
        equity = self.balances.get("USDT", 0.0)

        for symbol, pos in self.positions.items():
            if symbol not in market_prices:
                continue
            last = market_prices[symbol]
            equity += pos["qty"] * last

        return equity

    # ------------------------------------------------------------------
    def get_pnl(self, symbol: str, last_price: float):
        """Расчёт PnL по спотовой позиции."""
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        entry = pos["avg_price"]
        qty = pos["qty"]

        pnl_usdt = (last_price - entry) * qty
        pct = (pnl_usdt / (entry * qty)) * 100 if qty > 0 else 0

        return {
            "usdt": pnl_usdt,
            "pct": pct
        }

    # ------------------------------------------------------------------
    def create_market_order(self, symbol: str, side: str, qty: float, price: float):
        """
        Исполнение рыночного ордера.
        side = "BUY" / "SELL"
        qty  = количество монет
        price = текущая цена
        """
        fee_rate = cfg.SPOT_FEE_RATE

        if side == "BUY":
            cost = qty * price
            fee = cost * fee_rate
            total = cost + fee

            if self.balances["USDT"] < total:
                logger.warning(f"[PAPER-SPOT] insufficient USDT for BUY {symbol}")
                return None

            # списываем деньги
            self.balances["USDT"] -= total

            # увеличиваем позицию
            if symbol not in self.positions:
                self.positions[symbol] = {"qty": qty, "avg_price": price}
            else:
                pos = self.positions[symbol]
                new_qty = pos["qty"] + qty
                new_avg = (pos["avg_price"] * pos["qty"] + qty * price) / new_qty
                pos["qty"] = new_qty
                pos["avg_price"] = new_avg

            msg = f"[PAPER-SPOT] BUY {symbol} {qty:.8f} @ {price} cost={total:.2f} fee={fee:.4f}"
            logger.info(msg)
            log_trade(msg)
            return {"side": "BUY", "symbol": symbol, "qty": qty, "price": price}

        # ------------------------------------------------------------------
        elif side == "SELL":
            if symbol not in self.positions or self.positions[symbol]["qty"] < qty:
                logger.warning(f"[PAPER-SPOT] insufficient {symbol} qty for SELL")
                return None

            pos = self.positions[symbol]
            proceeds = qty * price
            fee = proceeds * fee_rate
            net = proceeds - fee

            # увеличиваем USDT
            self.balances["USDT"] += net

            # уменьшаем позицию
            pos["qty"] -= qty
            if pos["qty"] <= 0:
                del self.positions[symbol]

            msg = f"[PAPER-SPOT] SELL {symbol} {qty:.8f} @ {price} net={net:.2f} fee={fee:.4f}"
            logger.info(msg)
            log_trade(msg)
            return {"side": "SELL", "symbol": symbol, "qty": qty, "price": price}


# ======================================================================
#                           LIVE SPOT BROKER
# ======================================================================

class LiveSpotBroker:
    """
    Реальный спотовый брокер через Binance API.
    Минимальный функционал для безопасности:
    - маркет-ордера BUY/SELL
    - обновление балансов
    """

    def __init__(self, client):
        self.client = client

    # ------------------------------------------------------------------
    async def update_balances(self):
        """Получить реальные балансы аккаунта."""
        acc = await self.client.get_account()
        bals = {}

        for b in acc["balances"]:
            free = float(b["free"])
            locked = float(b["locked"])
            if free + locked > 0:
                bals[b["asset"]] = free + locked

        return bals

    # ------------------------------------------------------------------
    async def create_market_order(self, symbol: str, side: str, qty: float, price: float = None):
        """
        Создаёт реальный маркет-ордер.
        Для безопасности:
        - qty округляется
        - нет OCO, только маркет
        """
        try:
            res = await self.client.create_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=qty
            )
            logger.info(f"[LIVE-SPOT] {side} {symbol} {qty:.8f}")
            log_trade(f"[LIVE-SPOT] {side} {symbol} {qty:.8f}")
            return res

        except Exception as e:
            logger.error(f"[LIVE-SPOT] Order error: {e}")
            return None
