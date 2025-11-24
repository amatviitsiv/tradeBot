# strategy.py
import pandas as pd
import logging
import config as cfg

logger = logging.getLogger(__name__)


def _get_trend_regime(row_curr: pd.Series) -> str:
    price = row_curr["close"]
    sma_trend = row_curr["SMA_TREND"]
    ema_fast = row_curr["EMA_Fast"]
    ema_slow = row_curr["EMA_Slow"]
    adx = row_curr["ADX"]
    atr = row_curr["ATR"]

    # Если нет данных для тренда/ADX/ATR -> нет режима
    if pd.isna(sma_trend) or pd.isna(adx) or pd.isna(atr):
        return "none"

    # Anti-chop: рынок слишком "тихий" -> не торгуем
    atr_pct = atr / price if price else 0.0
    if atr_pct < cfg.ANTI_CHOP_MIN_ATR_PCT:
        return "none"

    # Требуем достаточную силу тренда
    if adx < cfg.ADX_TREND_THRESHOLD:
        return "none"

    # BULL режим
    if price > sma_trend and ema_fast > ema_slow:
        return "bull"

    # BEAR режим
    if price < sma_trend and ema_fast < ema_slow:
        return "bear"

    return "none"


def signal_from_indicators(df: pd.DataFrame):
    """
    Возвращает:
        "buy"  -> SPOT long
        "sell" -> FUTURES short
        None   -> без сделки
    """
    needed = max(cfg.SMA_TREND_PERIOD, cfg.EMA_SLOW, cfg.ADX_PERIOD) + 2
    if len(df) < needed:
        return None

    row_curr = df.iloc[-1]
    row_prev = df.iloc[-2]

    regime = _get_trend_regime(row_curr)

    ema_fast = row_curr["EMA_Fast"]
    ema_slow = row_curr["EMA_Slow"]
    ema_fast_prev = row_prev["EMA_Fast"]
    ema_slow_prev = row_prev["EMA_Slow"]

    macd_hist = row_curr.get("MACD_Hist", None)
    macd_hist_prev = row_prev.get("MACD_Hist", None)

    macd_bull_ok = (
        macd_hist is not None
        and macd_hist_prev is not None
        and macd_hist > macd_hist_prev
    )
    macd_bear_ok = (
        macd_hist is not None
        and macd_hist_prev is not None
        and macd_hist < macd_hist_prev
    )

    # BUY только в бычьем режиме
    if regime == "bull":
        crossed_up = ema_fast_prev <= ema_slow_prev and ema_fast > ema_slow
        if crossed_up and macd_bull_ok:
            return "buy"

    # SELL только в медвежьем режиме
    if regime == "bear":
        crossed_down = ema_fast_prev >= ema_slow_prev and ema_fast < ema_slow
        if crossed_down and macd_bear_ok:
            return "sell"

    return None
