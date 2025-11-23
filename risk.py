# risk.py

import config as cfg


class RiskManager:
    """
    Управление рисками:
    - размер спотовой позиции
    - размер фьючерсного шорта
    - риск на сделку
    - ограничение плеча
    """

    # -------------------------------------------------------------

    def calc_size(self, equity_usdt: float, entry_price: float):
        """
        Расчитывает размер позиции для СПОТА.
        Использует CAPITAL_ALLOCATION_PER_SYMBOL.

        Возвращает:
            (notional_usdt, qty)
        """
        if equity_usdt <= 0 or entry_price <= 0:
            return 0.0, 0.0

        notional = equity_usdt * cfg.CAPITAL_ALLOCATION_PER_SYMBOL
        qty = notional / entry_price

        return notional, qty

    # -------------------------------------------------------------

    def futures_notional(self, equity_usdt: float, leverage: int = None):
        """
        Расчитывает максимально допустимый фьючерсный notional.
        На основе риска и плеча.
        """

        if leverage is None:
            leverage = cfg.FUTURES_LEVERAGE_DEFAULT

        # Риск на сделку
        risk_limit = equity_usdt * cfg.RISK_PER_TRADE  # например 1% от equity

        # Notional позиции (USDT)
        # Цена смещения при стопе ≈ STOP_LOSS_PCT от цены
        if cfg.STOP_LOSS_PCT > 0:
            max_notional = risk_limit / cfg.STOP_LOSS_PCT
        else:
            max_notional = equity_usdt * leverage

        # Ограничиваем максимумом
        max_notional = min(max_notional, cfg.FUTURES_NOTIONAL_LIMIT)

        return max_notional

    # -------------------------------------------------------------

    def futures_qty(self, entry_price: float, equity_usdt: float, leverage: int = None):
        """
        Конвертирует futures notional → количество.
        """

        if entry_price <= 0:
            return 0.0

        notional = self.futures_notional(equity_usdt, leverage)
        qty = notional / entry_price

        return notional, qty

    # -------------------------------------------------------------

    def dynamic_leverage(self, equity_usdt: float):
        """
        Динамическое плечо:
        - маленький депозит → большее плечо (до лимита)
        - большой депозит → меньшее плечо

        Пример логики:
        - < 2000 USDT → x7
        - 2000–5000 → x5
        - 5000–10000 → x3
        - > 10000 → x2
        """

        if equity_usdt < 2000:
            return min(7, cfg.FUTURES_LEVERAGE_DEFAULT)
        if equity_usdt < 5000:
            return min(5, cfg.FUTURES_LEVERAGE_DEFAULT)
        if equity_usdt < 10000:
            return 3
        return 2
