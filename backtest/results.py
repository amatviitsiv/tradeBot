import numpy as np
import pandas as pd

def analyze_results(trades: pd.DataFrame, initial_balance: float, final_balance: float):
    if trades.empty:
        return {"total_pnl": 0, "roi": 0, "max_drawdown": 0}

    pnl_series = trades["pnl"].cumsum()
    max_dd = (np.maximum.accumulate(pnl_series) - pnl_series).max()

    roi = ((final_balance / initial_balance) - 1) * 100

    return {
        "total_pnl": final_balance - initial_balance,
        "roi": roi,
        "max_drawdown": max_dd,
        "num_trades": len(trades)
    }
