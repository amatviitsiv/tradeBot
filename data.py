# data.py
import pandas as pd
from binance import AsyncClient

async def fetch_klines_async(api_key: str, api_secret: str, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    """
    Fetch klines via AsyncClient and return pandas DataFrame with numeric columns.
    """
    client = await AsyncClient.create(api_key, api_secret)
    try:
        raw = await client.get_klines(symbol=symbol, interval=interval, limit=limit)
    finally:
        await client.close_connection()

    df = pd.DataFrame(raw, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_asset_volume","num_trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ])
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df
