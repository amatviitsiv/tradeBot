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

    def __init__(self, symbol, entry_price, qty, notional, mode="spot"):
        self.symbol = symbol                  # BTCUSDT
        self.entry_price = float(entry_price) # цена входа
        self.qty = float(qty)                 # кол-во актива
        self.notional = float(notional)       # стоимость позиции
        self.mode = mode                      # spot / futures
        self.open_time = time.time()          # timestamp открытия

        # Трейлинг-логика
        self.peak_price = entry_price         # максимум после входа
        self.trailing_stop = None             # будет активирован позже

    # ------------------------------------------------------------------
    def update_peak(self, last_price):
        """Обновляет максимальную цену движения (peak)."""
        if last_price > self.peak_price:
            self.peak_price = last_price

    # ------------------------------------------------------------------
    def current_stop(self, static_stop_pct):
        """
        Возвращает текущий уровнь стопа:
        - если трейлинг активирован → трейлинг-стоп
        - иначе статический стоп-лосс
        """
        if self.trailing_stop is not None:
            return self.trailing_stop

        return self.entry_price * (1 - static_stop_pct)

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
        }

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict):
        """Десериализация позиции при загрузке из state файла."""
        obj = cls(
            symbol=data["symbol"],
            entry_price=data["entry_price"],
            qty=data["qty"],
            notional=data["notional"],
            mode=data.get("mode", "spot"),
        )
        obj.open_time = data.get("open_time", time.time())
        obj.peak_price = data.get("peak_price", obj.entry_price)
        obj.trailing_stop = data.get("trailing_stop", None)
        return obj

    # ------------------------------------------------------------------
    def __repr__(self):
        return f"<Position {self.symbol} {self.mode} qty={self.qty} entry={self.entry_price}>"
