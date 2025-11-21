import config as cfg
from indicators import EMA, SMA, RSI, MACD, ATR
import numpy as np

def compute_indicators(df):
    df = df.copy()
    close = df['close']
    df[f'ema_{cfg.EMA_FAST}'] = EMA(close, cfg.EMA_FAST)
    df[f'ema_{cfg.EMA_SLOW}'] = EMA(close, cfg.EMA_SLOW)
    df[f'sma_{cfg.SMA}'] = SMA(close, cfg.SMA)
    df[f'rsi_{cfg.RSI_PERIOD}'] = RSI(close, cfg.RSI_PERIOD)
    macd_line, macd_signal, macd_hist = MACD(close, cfg.MACD_FAST, cfg.MACD_SLOW, cfg.MACD_SIGNAL)
    df['macd_line'] = macd_line
    df['macd_signal'] = macd_signal
    df['macd_hist'] = macd_hist
    df['atr'] = ATR(df, cfg.ATR_PERIOD)
    return df

def macd_zero_cross(prev_row, row):
    return prev_row['macd_line'] < 0 and row['macd_line'] > 0

def should_pyramid(pos, last_price):
    if pos.levels >= cfg.MAX_PYRAMID_LEVELS:
        return False
    if last_price >= pos.entry_price * (1 + 0.005):
        return True
    return False

def signal_from_indicators(df):
    if len(df) < max(cfg.EMA_SLOW, cfg.SMA) + 5:
        return None
    row = df.iloc[-1]
    prev = df.iloc[-2]
    ema_fast = row.get(f'ema_{cfg.EMA_FAST}')
    ema_slow = row.get(f'ema_{cfg.EMA_SLOW}')
    sma = row.get(f'sma_{cfg.SMA}')
    rsi = row.get(f'rsi_{cfg.RSI_PERIOD}')
    macd_hist = row.get('macd_hist')
    macd_line = row.get('macd_line')
    atr = row.get('atr')
    if any(x is None or (isinstance(x, float) and np.isnan(x)) for x in [ema_fast, ema_slow, sma, rsi, macd_hist, macd_line, atr]):
        return None

    # ATR volatility filter
    if (atr / row['close']) < cfg.ATR_MIN_PCT:
        return None

    trend_bull = row['close'] > ema_slow and ema_fast > ema_slow
    trend_bear = row['close'] < ema_slow and ema_fast < ema_slow

    macd_cross = macd_zero_cross(prev, row)
    prev_rsi = prev.get(f'rsi_{cfg.RSI_PERIOD}')
    rsi_recovering = prev_rsi is not None and prev_rsi < rsi

    buy = False
    sell = False

    if trend_bull and (macd_cross or macd_hist > 0) and (rsi <= cfg.RSI_OVERSOLD or rsi_recovering):
        buy = True

    if trend_bear or (macd_line < 0 and macd_hist < 0) or rsi >= cfg.RSI_OVERBOUGHT:
        sell = True

    if buy:
        return "buy"
    if sell:
        return "sell"
    return None
