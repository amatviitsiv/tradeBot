import config as cfg

class RiskManager:
    def calc_size(self, equity_usdt: float, entry_price: float):
        stop_price = entry_price * (1 - cfg.STOP_LOSS_PCT)
        risk_allowed = equity_usdt * cfg.RISK_PER_TRADE
        price_diff = abs(entry_price - stop_price)
        if price_diff == 0:
            return 0.0, 0.0
        notional = (risk_allowed * entry_price) / price_diff
        if notional < cfg.MIN_TRADE_USDT:
            return 0.0, 0.0
        qty = notional / entry_price
        return notional, qty

    def futures_notional_by_balance(self, balance_usdt: float, leverage: int, risk_frac: float):
        return balance_usdt * leverage * risk_frac
