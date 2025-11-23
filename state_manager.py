# state_manager.py

import json
import os
import logging

logger = logging.getLogger(__name__)


class StateManager:
    """
    Управляет файлом состояния:
    - сохраняет открытые позиции
    - загружает состояние при старте бота
    """

    def __init__(self, state_file: str):
        self.state_file = state_file
        self.data = {
            "positions": {}
        }

    # ----------------------------------------------------------------------
    def load(self):
        """Загружает состояние из JSON-файла."""
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
        """Сохраняет состояние (позиции) в JSON-файл."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.data, f, indent=4)
            logger.info(f"[STATE] Saved: {self.state_file}")
        except Exception as e:
            logger.error(f"[STATE] Failed to save state: {e}")

    # ----------------------------------------------------------------------
    def get_positions(self):
        """Возвращает словарь позиций."""
        return self.data.get("positions", {})

    # ----------------------------------------------------------------------
    def set_position(self, symbol: str, pos_dict: dict):
        """Добавляет или обновляет позицию."""
        self.data.setdefault("positions", {})
        self.data["positions"][symbol] = pos_dict
        self.save()

    # ----------------------------------------------------------------------
    def del_position(self, symbol: str):
        """Удаляет позицию при закрытии."""
        if symbol in self.data.get("positions", {}):
            del self.data["positions"][symbol]
            self.save()
