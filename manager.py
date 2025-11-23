# manager.py

import asyncio
import logging
import time

from binance import AsyncClient, BinanceSocketManager

import config as cfg
from utils import fetch_klines_async, sleep_corrected
from indicators import compute_indicators
from strategy import signal_from_indicators
from broker_spot import PaperSpotBroker, LiveSpotBroker
from broker_futures import PaperFuturesBroker, LiveFuturesBroker
from risk import RiskManager
from position import PositionState
from state_manager import StateManager
from telegram_notify import TelegramNotifier

from logger_setup import setup_logger

log = setup_logger("MANAGER", cfg.LOG_FILE)
trade_log = setup_logger("TRADE", cfg.TRADES_LOG_FILE)
error_log = setup_logger("ERROR", cfg.ERROR_LOG_FILE, level=logging.ERROR)

logger = logging.getLogger(__name__)

class Manager:
    """
    Основной управляющий класс:
    - инициализирует клиентов/брокеров
    - стримит цены (WS)
    - тянет свечи для индикаторов
    - принимает решение buy/sell
    - открывает/закрывает SPOT и FUTURES позиции
    - ведёт trailing/SL/TP
    - шлёт Telegram-уведомления
    - сохраняет состояние в файл
    """

    def __init__(self):
        self.client: AsyncClient | None = None
        self.bm: BinanceSocketManager | None = None

        self.spot_broker = None
        self.futures_broker = None

        self.risk = RiskManager()
        self.state = StateManager(cfg.STATE_FILE)

        self.positions: dict[str, PositionState] = {}
        self.market_prices: dict[str, float] = {}

        self.notifier = TelegramNotifier(cfg.TELEGRAM_TOKEN, cfg.TELEGRAM_CHAT_ID)
        self._last_equity_notify = 0.0

    # ------------------------------------------------------------------ #
    async def init(self):
        """
        Инициализация:
        - Binance AsyncClient
        - брокеры (paper / live)
        - загрузка позиций из state-файла
        - запуск Telegram-сессии
        """

        if cfg.REAL_TRADING:
            self.client = await AsyncClient.create(cfg.API_KEY, cfg.API_SECRET)
            self.spot_broker = LiveSpotBroker(self.client)
            self.futures_broker = LiveFuturesBroker(self.client)
            logger.info("[MANAGER] Live mode initialized")
        else:
            # без ключей тоже можно использовать AsyncClient,
            # он будет только читать данные
            self.client = await AsyncClient.create()
            self.spot_broker = PaperSpotBroker(cfg.INITIAL_BALANCE_USDT)
            self.futures_broker = PaperFuturesBroker()
            logger.info("[MANAGER] PAPER mode initialized")

        # загрузка состояния
        self.state.load()
        for s, p in self.state.get_positions().items():
            try:
                self.positions[s] = PositionState.from_dict(p)
                logger.info(f"[MANAGER] Restored position {self.positions[s]}")
            except Exception as e:
                logger.warning(f"[MANAGER] Failed to restore pos for {s}: {e}")

        await self.notifier.start()

        self.bm = BinanceSocketManager(self.client)

    # ------------------------------------------------------------------ #
    async def run(self):
        """
        Точка входа: инициализация + запуск WS и цикла стратегии.
        """
        await self.init()

        tasks = []

        # WS по тикам для всех символов
        for sym in cfg.SPOT_SYMBOLS:
            tasks.append(asyncio.create_task(self._ticker_listener(sym)))

        # Цикл оценки стратегии
        tasks.append(asyncio.create_task(self._evaluation_loop()))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    # ------------------------------------------------------------------ #
    async def shutdown(self):
        """Корректное завершение работы."""
        logger.info("[MANAGER] Shutting down...")
        self.state.save()
        await self.notifier.send("Bot stopped")
        await self.notifier.close()
        if self.client:
            await self.client.close_connection()

    # ------------------------------------------------------------------ #
    async def _ticker_listener(self, symbol: str):
        """
        Подписка на тикер по символу:
        обновляет self.market_prices[symbol]
        """
        assert self.bm is not None
        try:
            async with self.bm.symbol_ticker_socket(symbol) as stream:
                logger.info(f"[WS] ticker stream opened for {symbol}")
                while True:
                    try:
                        msg = await stream.recv()
                        if not isinstance(msg, dict):
                            continue
                        price_s = msg.get("c")
                        if price_s is None:
                            continue
                        price = float(price_s)
                        self.market_prices[symbol] = price
                    except Exception as e:
                        logger.exception(f"[WS] error in ticker {symbol}: {e}")
                        await self.notifier.send(f"WebSocket error for {symbol}: {e}")
                        await asyncio.sleep(1)
        except Exception as e:
            logger.exception(f"[WS] failed to open ticker for {symbol}: {e}")
            await self.notifier.send(f"WebSocket failed to open for {symbol}: {e}")

    # ------------------------------------------------------------------ #
    async def _evaluation_loop(self):
        """
        Основной стратегический цикл:
        - тянем свечи
        - считаем индикаторы
        - получаем сигнал buy/sell
        - управляем позициями
        - логируем PnL
        - шлём equity в телегу
        """
        while True:
            start = time.time()
            mp = dict(self.market_prices)

            for symbol in cfg.SPOT_SYMBOLS:
                last_price = mp.get(symbol)

                # ---- тянем свечи и считаем индикаторы ----
                try:
                    df = await fetch_klines_async(
                        self.client, symbol, cfg.TIMEFRAME, limit=cfg.HISTORY_LIMIT
                    )
                    df = compute_indicators(df)
                except Exception as e:
                    logger.exception(f"[MANAGER] failed to fetch klines for {symbol}: {e}")
                    await self.notifier.send(f"Failed fetching klines for {symbol}: {e}")
                    continue

                if len(df) < 3:
                    continue

                sig = signal_from_indicators(df)
                logger.info(f"[{symbol}] last={last_price} signal={sig} active={symbol in self.positions}")

                pos = self.positions.get(symbol)

                # ---- управление открытыми позициями (SL/TP/трейлинг) ----
                if pos and last_price:
                    await self._manage_open_position(symbol, pos, last_price)
                    # после _manage_open_position позиция могла быть закрыта
                    pos = self.positions.get(symbol)

                # ---- новая точка входа / переключение режимов ----
                if sig == "buy":
                    await self._handle_buy_signal(symbol, df, mp)
                elif sig == "sell":
                    await self._handle_sell_signal(symbol, df, mp)

            # ---- телеграм по equity ----
            await self._equity_notify(mp)
            # Log equity to console + main.log
            equity = self._calc_equity()
            log.info(f"[EQUITY] {equity:.2f} USDT")
            # ---- PnL логирование ----
            self._log_pnls(mp)

            # ---- пауза до следующего цикла ----
            await sleep_corrected(start, cfg.POLL_INTERVAL)

    # ------------------------------------------------------------------ #
    async def _manage_open_position(self, symbol: str, pos: PositionState, last_price: float):
        """
        Управление уже открытой позицией:
        - для SPOT: трейлинг / SL / TP
        - для FUTURES: SL/TP для шорта
        """
        # обновляем peak для трейлинга
        pos.update_peak(last_price)

        if pos.mode == "spot":
            # включаем трейлинг, когда профит > TRAILING_ACTIVATION_PCT
            profit_pct = (last_price - pos.entry_price) / pos.entry_price
            if pos.trailing_stop is None and profit_pct >= cfg.TRAILING_ACTIVATION_PCT:
                pos.trailing_stop = pos.entry_price * (1 - cfg.TRAILING_STOP_PCT)
                logger.info(f"[{symbol}] trailing armed stop={pos.trailing_stop:.6f}")

            # обновляем трейлинг стоп, если есть новый пик
            if pos.peak_price and pos.trailing_stop is not None:
                new_stop = pos.peak_price * (1 - cfg.TRAILING_STOP_PCT)
                if new_stop > pos.trailing_stop:
                    pos.trailing_stop = new_stop

            current_stop = pos.current_stop(cfg.STOP_LOSS_PCT)

            # стоп-лосс или трейлинг
            if last_price <= current_stop:
                logger.info(f"[{symbol}] Hit SPOT stop at {last_price:.2f} -> close")
                await self._close_position(symbol, pos, reason="STOP")
                return

            # тейк-профит
            tp_price = pos.entry_price * (1 + cfg.TAKE_PROFIT_PCT)
            if last_price >= tp_price:
                logger.info(f"[{symbol}] SPOT TP reached at {last_price:.2f} -> close")
                await self._close_position(symbol, pos, reason="TP")
                return

        else:
            # FUTURES SHORT логика:
            # TP: цена ниже entry на TAKE_PROFIT_PCT
            tp_price = pos.entry_price * (1 - cfg.TAKE_PROFIT_PCT)
            # SL: цена выше entry на STOP_LOSS_PCT
            sl_price = pos.entry_price * (1 + cfg.STOP_LOSS_PCT)

            if last_price <= tp_price:
                logger.info(f"[{symbol}] FUT TP (SHORT) at {last_price:.2f} -> close")
                await self._close_position(symbol, pos, reason="TP_SHORT")
                return

            if last_price >= sl_price:
                logger.info(f"[{symbol}] FUT SL (SHORT) at {last_price:.2f} -> close")
                await self._close_position(symbol, pos, reason="SL_SHORT")
                return

    # ------------------------------------------------------------------ #
    async def _handle_buy_signal(self, symbol: str, df, market_prices: dict):
        """
        BUY сигнал:
        - если был фьючерсный шорт → закрываем его
        - если нет позиции → открываем SPOT LONG
        """
        pos = self.positions.get(symbol)

        # если был фьючерсный шорт — закрываем и переключаемся
        if pos and pos.mode == "futures":
            await self._close_position(symbol, pos, reason="SWITCH_TO_SPOT")
            pos = None

        if pos:
            # уже есть SPOT позиция — можно сделать pyramid, но сейчас просто не лезем
            return

        # считаем equity
        equity = await self._get_equity(market_prices)

        entry_price = df["close"].iloc[-1]
        notional, qty = self.risk.calc_size(equity, entry_price)
        if notional <= 0 or qty <= 0:
            logger.info(f"[{symbol}] calc_size too small, skip BUY")
            return

        # отправляем ордер
        if cfg.REAL_TRADING:
            await self.spot_broker.create_market_order(symbol, "BUY", qty, entry_price)
        else:
            self.spot_broker.create_market_order(symbol, "BUY", qty, entry_price)

        pos_state = PositionState(symbol, entry_price, qty, notional, mode="spot")
        self.positions[symbol] = pos_state
        self.state.set_position(symbol, pos_state.to_dict())

        logger.info(f"[{symbol}] Entered SPOT pos qty={qty:.8f} notional={notional:.2f}")
        await self.notifier.send(f"BUY {symbol} qty={qty:.6f} price={entry_price:.2f}")

    # ------------------------------------------------------------------ #
    async def _handle_sell_signal(self, symbol: str, df, market_prices: dict):
        """
        SELL сигнал:
        - если была SPOT позиция → закрываем её
        - если позиции нет → открываем FUTURES SHORT
        """
        pos = self.positions.get(symbol)

        # если есть SPOT — закрываем и переключаемся в фьючерсный шорт
        if pos and pos.mode == "spot":
            await self._close_position(symbol, pos, reason="SWITCH_TO_FUTURES")
            pos = None

        if pos:
            # уже есть шорт по фьючерсам — пока не добавляем pyramid в шорт
            return

        entry_price = df["close"].iloc[-1]

        equity = await self._get_equity(market_prices)
        leverage = self.risk.dynamic_leverage(equity)
        notional, qty = self.risk.futures_qty(entry_price, equity, leverage)
        if notional <= 0 or qty <= 0:
            logger.info(f"[{symbol}] futures size too small, skip SHORT")
            return

        if cfg.REAL_TRADING:
            await self.futures_broker.set_leverage(symbol, leverage)
            await self.futures_broker.create_market_order(
                symbol, "SELL", qty, entry_price, reduce_only=False
            )
        else:
            self.futures_broker.create_market_order(
                symbol, "SELL", qty, entry_price, reduce_only=False
            )

        pos_state = PositionState(symbol, entry_price, qty, notional, mode="futures")
        self.positions[symbol] = pos_state
        self.state.set_position(symbol, pos_state.to_dict())

        logger.info(f"[{symbol}] Entered FUTURES SHORT qty={qty:.8f} notional={notional:.2f} lev={leverage}x")
        await self.notifier.send(
            f"OPEN SHORT {symbol} qty={qty:.6f} price={entry_price:.2f} lev={leverage}x"
        )

    # ------------------------------------------------------------------ #
    async def _get_equity(self, market_prices: dict) -> float:
        """
        Считает equity:
        - в PAPER режиме → через PaperSpotBroker.get_equity
        - в LIVE режиме → через реальные балансы (spot)
        Фьючерсный PnL в LIVE мы здесь не учитываем (для простоты),
        в PAPER — считаем через PositionState отдельно.
        """
        if not cfg.REAL_TRADING:
            return self.spot_broker.get_equity(market_prices)

        # LIVE режим: собираем балансы
        try:
            balances = await self.spot_broker.update_balances()
        except Exception as e:
            logger.error(f"[MANAGER] failed to update balances: {e}")
            return cfg.INITIAL_BALANCE_USDT

        eq = 0.0
        for asset, amt in balances.items():
            if asset == "USDT":
                eq += amt
            else:
                sym = asset + "USDT"
                price = market_prices.get(sym)
                if price:
                    eq += amt * price

        return eq

    # ------------------------------------------------------------------ #
    async def _equity_notify(self, market_prices: dict):
        """
        Периодическая отправка equity в Telegram.
        """
        if cfg.TELEGRAM_EQUITY_INTERVAL_MIN <= 0:
            return

        now = time.time()
        if now - self._last_equity_notify < cfg.TELEGRAM_EQUITY_INTERVAL_MIN * 60:
            return

        eq = await self._get_equity(market_prices)
        await self.notifier.send(f"Equity: {eq:.2f} USDT")
        self._last_equity_notify = now

    # ------------------------------------------------------------------ #
    def _log_pnls(self, market_prices: dict):
        """
        Логирует PnL по всем открытым позициям.
        Используем self.market_prices, чтобы не зависеть от слепка mp,
        который мог быть снят до прихода цены по какому-то символу.
        """
        prices = dict(self.market_prices)  # берём самые свежие цены

        for s, p in list(self.positions.items()):
            last = prices.get(s)
            if last is None:
                # Для отладки можно включить лог:
                # logger.debug(f"[PNL] skip {s}, no last price yet")
                continue

            if p.mode == "spot":
                pnl = self.spot_broker.get_pnl(s, last)
                if pnl is not None:
                    logger.info(
                        f"[PNL-SPOT] {s} entry={p.entry_price:.2f} last={last:.2f} "
                        f"qty={p.qty:.6f} -> {pnl['usdt']:.2f}USDT ({pnl['pct']:.2f}%)"
                    )
            else:
                # PnL шорта: profit, когда цена падает
                pnl_usdt = (p.entry_price - last) * p.qty
                pnl_pct = (pnl_usdt / p.notional) * 100 if p.notional else 0.0
                logger.info(
                    f"[PNL-FUT] {s} entry={p.entry_price:.2f} last={last:.2f} "
                    f"qty={p.qty:.6f} -> {pnl_usdt:.2f}USDT ({pnl_pct:.2f}%)"
                )

    def _calc_equity(self):
        prices = self.market_prices
        total = 0.0

        if hasattr(self.spot_broker, "get_equity"):
            return self.spot_broker.get_equity(prices)

        # Если вдруг real spot broker
        for s, p in self.positions.items():
            last = prices.get(s)
            if last:
                if p.mode == "spot":
                    total += p.qty * last
                else:
                    total += p.notional + (p.entry_price - last) * p.qty

        return total

    # ------------------------------------------------------------------ #
    async def _close_position(self, symbol: str, pos: PositionState, reason: str = ""):
        """
        Закрывает SPOT или FUTURES позицию.
        """
        last = self.market_prices.get(symbol)
        if not last:
            logger.warning(f"[MANAGER] no last price for {symbol} on close")
            return

        if pos.mode == "spot":
            # закрываем спотовую
            if cfg.REAL_TRADING:
                await self.spot_broker.create_market_order(symbol, "SELL", pos.qty, last)
            else:
                self.spot_broker.create_market_order(symbol, "SELL", pos.qty, last)

            await self.notifier.send(
                f"CLOSED SPOT {symbol} qty={pos.qty:.6f} price={last:.2f} reason={reason}"
            )

        else:
            # закрываем фьючерсный шорт (BUY reduce_only)
            if cfg.REAL_TRADING:
                await self.futures_broker.create_market_order(
                    symbol, "BUY", pos.qty, last, reduce_only=True
                )
            else:
                self.futures_broker.create_market_order(
                    symbol, "BUY", pos.qty, last, reduce_only=True
                )

            await self.notifier.send(
                f"CLOSED FUTURES SHORT {symbol} qty={pos.qty:.6f} price={last:.2f} reason={reason}"
            )

        if symbol in self.positions:
            del self.positions[symbol]
        self.state.del_position(symbol)
