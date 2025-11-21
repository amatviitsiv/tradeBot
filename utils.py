import math, json, os
from typing import Tuple, Optional
import pandas as pd

async def fetch_klines_async(client, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    raw = await client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(raw, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_asset_volume","num_trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    return df

def split_symbol(symbol: str) -> Tuple[Optional[str], Optional[str]]:
    common_quotes = ["USDT", "BUSD", "USDC", "BTC", "ETH", "BNB"]
    for q in common_quotes:
        if symbol.endswith(q) and len(symbol) > len(q):
            return symbol[:-len(q)], q
    if len(symbol) >= 6:
        mid = len(symbol) // 2
        return symbol[:mid], symbol[mid:]
    return None, None

def round_down(value: float, step: Optional[float]) -> float:
    if not step or step == 0:
        return value
    precision = max(0, int(round(-math.log10(step))))
    return float(round(math.floor(value / step) * step, precision))

def save_state(path: str, state: dict):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)

def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)
