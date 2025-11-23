# indicators.py
import pandas as pd
import numpy as np
import config as cfg


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Считаем основные индикаторы для Dual Trend Bot:
    - EMA_Fast / EMA_Slow
    - SMA_TREND (SMA200) для определения бычьего/медвежьего рынка
    - ATR (волатильность)
    - ADX (сила тренда)
    - MACD (для дополнительного фильтра)
    Предполагается, что df содержит колонки: open, high, low, close.
    """

    df = df.copy()

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # --- EMA быстрый/медленный ---
    df["EMA_Fast"] = close.ewm(span=cfg.EMA_FAST, adjust=False).mean()
    df["EMA_Slow"] = close.ewm(span=cfg.EMA_SLOW, adjust=False).mean()

    # --- SMA трендовая (например, 200) ---
    df["SMA_TREND"] = close.rolling(window=cfg.SMA_TREND_PERIOD, min_periods=cfg.SMA_TREND_PERIOD).mean()

    # --- ATR ---
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["TR"] = tr
    df["ATR"] = df["TR"].rolling(window=cfg.ATR_PERIOD, min_periods=cfg.ATR_PERIOD).mean()

    # --- ADX ---
    # Расчёт +DM и -DM
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_smooth = tr.rolling(window=cfg.ADX_PERIOD, min_periods=cfg.ADX_PERIOD).sum()
    plus_dm_smooth = pd.Series(plus_dm, index=df.index).rolling(window=cfg.ADX_PERIOD, min_periods=cfg.ADX_PERIOD).sum()
    minus_dm_smooth = pd.Series(minus_dm, index=df.index).rolling(window=cfg.ADX_PERIOD, min_periods=cfg.ADX_PERIOD).sum()

    plus_di = 100 * (plus_dm_smooth / tr_smooth.replace(0, np.nan))
    minus_di = 100 * (minus_dm_smooth / tr_smooth.replace(0, np.nan))

    dx = 100 * ( (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) )
    df["ADX"] = dx.rolling(window=cfg.ADX_PERIOD, min_periods=cfg.ADX_PERIOD).mean()

    # --- MACD (для дополнительного фильтра) ---
    ema_fast_macd = close.ewm(span=12, adjust=False).mean()
    ema_slow_macd = close.ewm(span=26, adjust=False).mean()
    macd_line = ema_fast_macd - ema_slow_macd
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_signal

    df["MACD"] = macd_line
    df["MACD_Signal"] = macd_signal
    df["MACD_Hist"] = macd_hist

    return df
