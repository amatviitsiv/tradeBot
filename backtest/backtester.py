import sys
import os

# Добавляем корневую папку проекта в PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import logging
import time

from indicators import compute_indicators
from strategy import signal_from_indicators
from state_manager import Position

logger = logging.getLogger("backtest")

class Backtester:
    def __init__(self, df, symbol, initial_balance=5000):
        self.df = df.copy()
        self.symbol = symbol
        self.balance = initial_balance
        self.position = None
        self.trade_log = []

    def open_position(self, price, mode):
        qty = self.balance / price
        self.position = Position(
            symbol=self.symbol,
            entry_price=price,
            qty=qty,
            notional=self.balance,
            mode=mode,
            open_time=time.time(),
            peak_price=price,
            trailing_stop=None
        )
        logger.info(f"[BACKTEST] OPEN {mode.upper()} {self.symbol} @ {price} qty={qty:.4f}")

    def close_position(self, price):
        if not self.position:
            return

        pnl = (price - self.position.entry_price) * self.position.qty
        self.balance += pnl
        logger.info(f"[BACKTEST] CLOSE {self.position.symbol} PNL={pnl:.2f} → BAL={self.balance:.2f}")

        self.trade_log.append({
            "entry": self.position.entry_price,
            "exit": price,
            "qty": self.position.qty,
            "pnl": pnl,
        })

        self.position = None

    def run(self):
        df = compute_indicators(self.df)

        for _, row in df.iterrows():
            price = row["close"]

            signal = signal_from_indicators(df.loc[:_, :])

            # --- логика BUY ---
            if signal == "buy" and not self.position:
                self.open_position(price, mode="spot")

            # --- логика SELL ---
            elif signal == "sell" and self.position:
                self.close_position(price)

        # Закрыть открытые позиции в конце
        if self.position:
            self.close_position(df.iloc[-1]["close"])

        return self.balance, pd.DataFrame(self.trade_log)
