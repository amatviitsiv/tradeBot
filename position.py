# position.py

import time
import json

class PositionState:
    """
    Универсальное состояние позиции бота.
    Поддерживает:
    - spot режим (mode="spot")
    - futures short режим (mode="futures")
    """

    def __init__(
        self,
        symbol: str,
        entry_price: float,
        qty: float,
        notional: float,
        mode: str = "spot",
        open_time: float = None,
        peak_price: float = None,
        trailing_stop: float = None,
        pyramid_level: int = 0,
    ):
        self.symbol = symbol
        self.entry_price = entry_price
        self.qty = qty
        self.notional = notional
        self.mode = mode  # "spot" или "futures"
        self.open_time = open_time or time.time()
        self.peak_price = peak_price if peak_price is not None else entry_price
        self.trailing_stop = trailing_stop
        self.pyramid_level = pyramid_level

    # ------------------------------------------------------------------
    def update_peak(self, last_price: float):
        if last_price > (self.peak_price or self.entry_price):
            self.peak_price = last_price

    # ------------------------------------------------------------------
    def current_stop(self, stop_loss_pct: float) -> float:
        """
        Возвращает актуальный стоп:
        - либо фиксированный от entry_price
        - либо trailing_stop, если он уже "вооружён"
        """
        base_sl = self.entry_price * (1 - stop_loss_pct)
        if self.trailing_stop is None:
            return base_sl
        return max(base_sl, self.trailing_stop)

    # ------------------------------------------------------------------
    def to_dict(self):
        """Сериализация позиции для StateManager."""
        return {
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "qty": self.qty,
            "notional": self.notional,
            "mode": self.mode,
            "open_time": self.open_time,
            "peak_price": self.peak_price,
            "trailing_stop": self.trailing_stop,
            "pyramid_level": self.pyramid_level,
        }

    def add_layer(self, price: float, qty_add: float, notional_add: float):
        """
        Smart re-entry: добавляем объём по новой цене,
        пересчитываем среднюю цену входа.
        """
        total_notional_before = self.entry_price * self.qty
        total_notional_after = total_notional_before + notional_add
        total_qty_after = self.qty + qty_add

        if total_qty_after > 0:
            self.entry_price = total_notional_after / total_qty_after

        self.qty = total_qty_after
        self.notional += notional_add
        # пирамидальный уровень увеличиваем
        self.pyramid_level += 1

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            symbol=d["symbol"],
            entry_price=d["entry_price"],
            qty=d["qty"],
            notional=d["notional"],
            mode=d.get("mode", "spot"),
            open_time=d.get("open_time"),
            peak_price=d.get("peak_price"),
            trailing_stop=d.get("trailing_stop"),
            pyramid_level=d.get("pyramid_level", 0),
        )

    # ------------------------------------------------------------------
    def __repr__(self):
        return f"<Position {self.symbol} {self.mode} qty={self.qty} entry={self.entry_price}>"
