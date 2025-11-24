# state_manager.py

import json
import os
import logging
import time

logger = logging.getLogger(__name__)


class Position:
    """
    Универсальная модель позиции для спота и фьючерсов.
    Используется и в реальной торговле, и в бэктестинге.
    """

    def __init__(
        self,
        symbol: str,
        entry_price: float,
        qty: float,
        notional: float,
        mode: str,            # "spot" или "futures"
        open_time: float = None,
        peak_price: float = None,
        trailing_stop: float = None,
    ):
        self.symbol = symbol
        self.entry_price = entry_price
        self.qty = qty
        self.notional = notional
        self.mode = mode
        self.open_time = open_time or time.time()

        # Для трейлинг-стопа
        self.peak_price = peak_price or entry_price
        self.trailing_stop = trailing_stop

    # ----------------------------------------------------
    def to_dict(self):
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

    @staticmethod
    def from_dict(d: dict):
        return Position(
            symbol=d["symbol"],
            entry_price=d["entry_price"],
            qty=d["qty"],
            notional=d["notional"],
            mode=d["mode"],
            open_time=d.get("open_time"),
            peak_price=d.get("peak_price"),
            trailing_stop=d.get("trailing_stop"),
        )


class StateManager:
    """
    Управляет файлом состояния:
    - сохраняет открытые позиции
    - загружает состояние при старте бота
    """

    def __init__(self, state_file: str):
        self.state_file = state_file
        self.data = {"positions": {}}

    # ----------------------------------------------------------------------
    def load(self):
        if not os.path.exists(self.state_file):
            logger.info(f"[STATE] No state file found, starting fresh.")
            return

        try:
            with open(self.state_file, "r") as f:
                self.data = json.load(f)
            logger.info(f"[STATE] Loaded: {self.state_file}")
        except Exception as e:
            logger.error(f"[STATE] Failed to load {self.state_file}: {e}")
            self.data = {"positions": {}}

    # ----------------------------------------------------------------------
    def save(self):
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.data, f, indent=4)
            logger.info(f"[STATE] Saved: {self.state_file}")
        except Exception as e:
            logger.error(f"[STATE] Failed to save state: {e}")

    # ----------------------------------------------------------------------
    def get_positions(self):
        return self.data.get("positions", {})

    # ----------------------------------------------------------------------
    def set_position(self, symbol: str, pos: Position):
        """
        Добавляет или обновляет позицию. pos = объект Position
        """
        self.data.setdefault("positions", {})
        self.data["positions"][symbol] = pos.to_dict()
        self.save()

    # ----------------------------------------------------------------------
    def del_position(self, symbol: str):
        if symbol in self.data.get("positions", {}):
            del self.data["positions"][symbol]
            self.save()

    # ----------------------------------------------------------------------
    def load_position_objects(self) -> dict:
        """
        Преобразует JSON позиции в объекты Position.
        Используется в реальном боте и бэктестере.
        """
        positions = self.data.get("positions", {})
        return {sym: Position.from_dict(p) for sym, p in positions.items()}
