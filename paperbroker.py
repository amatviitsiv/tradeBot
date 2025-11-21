import logging
log = logging.getLogger(__name__)

class PaperBroker:
    def __init__(self, start_balance):
        self.balances = {"USDT": start_balance}
        self.prices = {}

    def get_balance(self, asset):
        return self.balances.get(asset, 0)

    def update_price(self, symbol, price):
        self.prices[symbol] = price

    def get_equity(self):
        equity = 0
        for asset, amount in self.balances.items():
            if asset == "USDT":
                equity += amount
            else:
                price = self.prices.get(f"{asset}USDT", 0)
                equity += amount * price
        return equity

    def market_order(self, symbol, side, qty, price):
        base, quote = symbol[:-4], symbol[-4:]
        if side == "BUY":
            cost = qty * price
            if self.balances.get(quote, 0) >= cost:
                self.balances[quote] -= cost
                self.balances[base] = self.balances.get(base, 0) + qty
                log.info(f"[PAPER] BUY {symbol} {qty:.4f} @ {price:.2f}")
        elif side == "SELL":
            if self.balances.get(base, 0) >= qty:
                self.balances[base] -= qty
                self.balances[quote] = self.balances.get(quote, 0) + qty * price
                log.info(f"[PAPER] SELL {symbol} {qty:.4f} @ {price:.2f}")
