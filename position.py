class PositionState:
    def __init__(self, symbol: str, entry_price: float, qty: float, notional: float, mode: str = "spot"):
        self.symbol = symbol
        self.entry_price = entry_price
        self.qty = qty
        self.notional = notional
        self.mode = mode
        self.levels = 1
        self.peak_price = entry_price
        self.trailing_stop = None

    def update_peak(self, price: float):
        if price > self.peak_price:
            self.peak_price = price

    def current_stop(self, stop_loss_pct: float):
        if self.trailing_stop is not None:
            return self.trailing_stop
        return self.entry_price * (1 - stop_loss_pct)

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "qty": self.qty,
            "notional": self.notional,
            "mode": self.mode,
            "levels": self.levels,
            "peak_price": self.peak_price,
            "trailing_stop": self.trailing_stop
        }

    @staticmethod
    def from_dict(d):
        p = PositionState(d["symbol"], d["entry_price"], d["qty"], d["notional"], d.get("mode", "spot"))
        p.levels = d.get("levels", 1)
        p.peak_price = d.get("peak_price", p.entry_price)
        p.trailing_stop = d.get("trailing_stop", None)
        return p
