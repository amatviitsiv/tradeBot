import pandas as pd
from copy import deepcopy

from strategy import compute_indicators, signal_from_indicators
from manager import Manager
import config as cfg


class Backtester:
    def __init__(self, symbol: str, df: pd.DataFrame):
        self.symbol = symbol
        self.df = df
        self.manager = Manager(backtest_mode=True)

        # отключаем вебсокеты и API
        self.manager.market_prices = {}
        self.manager.client = None

        # backtest equity
        self.equity_curve = []

    # -----------------------------------------------------------
    def run(self):
        """
        Прогоняет стратегию по историческим свечам.
        Полностью симулирует реальный бот.
        """
        for idx in range(len(self.df)):
            row = self.df.iloc[: idx + 1]

            # обновляем историю в стиле fetch_klines
            df = compute_indicators(row.copy())
            last_price = df["close"].iloc[-1]

            self.manager.market_prices[self.symbol] = last_price

            sig = signal_from_indicators(df)

            pos = self.manager.positions.get(self.symbol)

            # управление активной позицией
            if pos:
                self.manager._manage_existing_position(self.symbol, pos, last_price)
                self.manager._maybe_pyramid_spot(self.symbol, pos, last_price, sig)

            # сигналы
            if sig == "buy":
                self.manager._process_buy_signal(self.symbol, df, last_price)

            elif sig == "sell":
                self.manager._process_sell_signal(self.symbol, df, last_price)

            # запоминаем equity
            equity = self.manager._calc_equity()
            self.equity_curve.append(equity)

        result = {
            "symbol": self.symbol,
            "final_equity": self.equity_curve[-1],
            "pnl_total": self.equity_curve[-1] - cfg.INITIAL_BALANCE_USDT,
            "roi": (self.equity_curve[-1] / cfg.INITIAL_BALANCE_USDT - 1) * 100,
        }
        return result
