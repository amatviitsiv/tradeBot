# broker_futures.py

import logging
import config as cfg
from utils import log_trade

logger = logging.getLogger(__name__)


# ======================================================================
#                         PAPER FUTURES BROKER
# ======================================================================

class PaperFuturesBroker:
    """
    Упрощённый фьючерсный брокер для PAPER режима.
    Моделируем только шорты:
    - side="SELL"  => открываем/увеличиваем SHORT
    - side="BUY"   => закрываем/уменьшаем SHORT (reduce_only)
    Баланс отдельно не ведём — PnL считаем в Manager по entry/last.
    """

    def __init__(self):
        # symbol -> qty (SHORT объём, всегда >= 0, это "кол-во в шорте")
        self.positions = {}
        logger.info("[PAPER-FUT] initialized")

    def create_market_order(self, symbol: str, side: str, qty: float, price: float, reduce_only: bool = False):
        """
        Исполняет "виртуальный" маркет-ордер.
        Возвращает словарь с параметрами ордера для логов/аналитики.
        """
        fee_rate = cfg.FUTURES_FEE_RATE
        notional = qty * price
        fee = notional * fee_rate

        if side == "SELL" and not reduce_only:
            # Открываем/увеличиваем шорт
            cur = self.positions.get(symbol, 0.0)
            new_qty = cur + qty
            self.positions[symbol] = new_qty
            msg = (
                f"[PAPER-FUT] OPEN/ADD SHORT {symbol} qty={qty:.6f} "
                f"@ {price:.4f} notional={notional:.2f} fee={fee:.4f} total_short={new_qty:.6f}"
            )
            logger.info(msg)
            log_trade(msg)
            return {
                "side": "SELL",
                "symbol": symbol,
                "qty": qty,
                "price": price,
                "notional": notional,
                "fee": fee,
                "mode": "open_short"
            }

        elif side == "BUY":
            # Считаем, что BUY уменьшает или закрывает шорт
            cur = self.positions.get(symbol, 0.0)
            closed_qty = min(cur, qty)
            new_qty = max(0.0, cur - qty)
            self.positions[symbol] = new_qty
            action = "CLOSE SHORT" if new_qty == 0 else "REDUCE SHORT"

            msg = (
                f"[PAPER-FUT] {action} {symbol} qty={closed_qty:.6f} "
                f"@ {price:.4f} notional={notional:.2f} fee={fee:.4f} remaining_short={new_qty:.6f}"
            )
            logger.info(msg)
            log_trade(msg)
            return {
                "side": "BUY",
                "symbol": symbol,
                "qty": closed_qty,
                "price": price,
                "notional": notional,
                "fee": fee,
                "mode": "close_short"
            }

        else:
            msg = f"[PAPER-FUT] Unsupported side={side} for {symbol}"
            logger.warning(msg)
            log_trade(msg)
            return None


# ======================================================================
#                         LIVE FUTURES BROKER
# ======================================================================

class LiveFuturesBroker:
    """
    Реальный фьючерсный брокер для Binance USDT-M Futures.
    ОЧЕНЬ ВАЖНО: использовать аккуратно (REAL_TRADING=True).
    """

    def __init__(self, client):
        """
        client — это объект AsyncClient из python-binance
        """
        self.client = client

    # ------------------------------------------------------------------
    async def update_balance(self):
        """
        Получить балансы фьючерсного аккаунта.
        Возвращает dict: asset -> balance
        """
        balances = {}
        try:
            acc = await self.client.futures_account_balance()
            for b in acc:
                asset = b["asset"]
                bal = float(b["balance"])
                if bal != 0:
                    balances[asset] = bal
        except Exception as e:
            logger.error(f"[LIVE-FUT] update_balance error: {e}")
            return {}
        return balances

    # ------------------------------------------------------------------
    async def set_leverage(self, symbol: str, leverage: int):
        """
        Устанавливает плечо для символа.
        """
        lev = int(max(1, min(leverage, cfg.FUTURES_LEVERAGE_DEFAULT)))
        try:
            res = await self.client.futures_change_leverage(
                symbol=symbol,
                leverage=lev
            )
            logger.info(f"[LIVE-FUT] set leverage {symbol} -> x{lev}")
            return res
        except Exception as e:
            logger.error(f"[LIVE-FUT] set_leverage error {symbol}: {e}")
            return None

    # ------------------------------------------------------------------
    async def create_market_order(self, symbol: str, side: str, qty: float, price: float = None, reduce_only: bool = False):
        """
        Создаёт реальный маркет-ордер на Binance Futures.
        Для шортов:
            side="SELL", reduce_only=False   -> открыть/увеличить шорт
            side="BUY",  reduce_only=True    -> закрыть шорт (reduce-only)
        """

        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "reduceOnly": reduce_only
        }

        try:
            res = await self.client.futures_create_order(**params)
            msg = f"[LIVE-FUT] {side} {symbol} qty={qty:.6f} reduce_only={reduce_only}"
            logger.info(msg)
            log_trade(msg)
            return res
        except Exception as e:
            logger.error(f"[LIVE-FUT] order error {symbol}: {e}")
            return None
