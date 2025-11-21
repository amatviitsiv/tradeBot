import config as cfg
from utils import save_state, load_state
import time

DEFAULT = {
    "positions": {},
    "equity": cfg.INITIAL_BALANCE_USDT,
    "last_update": None,
    "trade_counts": {}
}

class StateManager:
    def __init__(self, path=cfg.STATE_FILE):
        self.path = path
        s = load_state(self.path)
        self.state = s if s else DEFAULT.copy()
        for k in DEFAULT:
            if k not in self.state:
                self.state[k] = DEFAULT[k]
        if self.state.get("last_update") is None:
            self.state["last_update"] = time.time()

    def save(self):
        self.state["last_update"] = time.time()
        save_state(self.path, self.state)

    def get_positions(self):
        return self.state.get("positions", {})

    def set_position(self, symbol, posdict):
        self.state.setdefault("positions", {})
        self.state["positions"][symbol] = posdict
        self.save()

    def del_position(self, symbol):
        if "positions" in self.state and symbol in self.state["positions"]:
            del self.state["positions"][symbol]
            self.save()

    def set_equity(self, eq):
        self.state["equity"] = eq
        self.save()

    def incr_trade_count(self, symbol):
        tc = self.state.setdefault("trade_counts", {})
        tc[symbol] = tc.get(symbol, 0) + 1
        self.save()

    def get_trade_count(self, symbol):
        return self.state.get("trade_counts", {}).get(symbol, 0)
