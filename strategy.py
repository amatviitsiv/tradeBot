# strategy.py
"""
Dual Trend Bot стратегия.

Идея:
- Определяем РЕЖИМ рынка по каждой паре:
    BULL (бычий), если:
        цена > SMA_TREND
        EMA_Fast > EMA_Slow
        ADX >= ADX_TREND_THRESHOLD

    BEAR (медвежий), если:
        цена < SMA_TREND
        EMA_Fast < EMA_Slow
        ADX >= ADX_TREND_THRESHOLD

- Входим:
    BUY  (SPOT)  только в режиме BULL и только в момент,
                 когда EMA_Fast пересекает EMA_Slow снизу вверх.
    SELL (FUT)   только в режиме BEAR и только в момент,
                 когда EMA_Fast пересекает EMA_Slow сверху вниз.

- Если режим отсутствует (флэт, слабый тренд) -> сигнала нет.
"""

import pandas as pd
import logging
import config as cfg

logger = logging.getLogger(__name__)


def _get_trend_regime(row_curr, row_prev):
    price = row_curr["close"]
    sma_trend = row_curr["SMA_TREND"]
    ema_fast = row_curr["EMA_Fast"]
    ema_slow = row_curr["EMA_Slow"]
    adx = row_curr["ADX"]

    # Если ещё нет достаточного количества данных для SMA/ADX
    if pd.isna(sma_trend) or pd.isna(adx):
        return "none"

    strong_trend = adx >= cfg.ADX_TREND_THRESHOLD

    if strong_trend and price > sma_trend and ema_fast > ema_slow:
        return "bull"
    if strong_trend and price < sma_trend and ema_fast < ema_slow:
        return "bear"

    return "none"


def signal_from_indicators(df: pd.DataFrame):
    """
    Возвращает:
        "buy"   -> открываем SPOT long (менеджер уже это умеет)
        "sell"  -> открываем FUTURES short (менеджер тоже умеет)
        None    -> ничего не делаем
    """
    if len(df) < max(cfg.SMA_TREND_PERIOD, cfg.EMA_SLOW, cfg.ADX_PERIOD) + 2:
        return None

    row_curr = df.iloc[-1]
    row_prev = df.iloc[-2]

    regime = _get_trend_regime(row_curr, row_prev)

    ema_fast = row_curr["EMA_Fast"]
    ema_slow = row_curr["EMA_Slow"]
    ema_fast_prev = row_prev["EMA_Fast"]
    ema_slow_prev = row_prev["EMA_Slow"]

    macd_hist = row_curr.get("MACD_Hist", None)
    macd_hist_prev = row_prev.get("MACD_Hist", None)

    # Доп. фильтр по MACD: хотим, чтобы он двигался в нужную сторону
    macd_bull_ok = macd_hist is not None and macd_hist_prev is not None and macd_hist > macd_hist_prev
    macd_bear_ok = macd_hist is not None and macd_hist_prev is not None and macd_hist < macd_hist_prev

    # --- BUY (SPOT) только в бычьем режиме ---
    if regime == "bull":
        # классический cross снизу вверх
        crossed_up = ema_fast_prev <= ema_slow_prev and ema_fast > ema_slow
        if crossed_up and macd_bull_ok:
            # logger.info(f"[STRATEGY] BULL buy signal, regime=bull, ema_fast={ema_fast}, ema_slow={ema_slow}")
            return "buy"

    # --- SELL (FUTURES SHORT) только в медвежьем режиме ---
    if regime == "bear":
        crossed_down = ema_fast_prev >= ema_slow_prev and ema_fast < ema_slow
        if crossed_down and macd_bear_ok:
            # logger.info(f"[STRATEGY] BEAR sell signal, regime=bear, ema_fast={ema_fast}, ema_slow={ema_slow}")
            return "sell"

    return None
