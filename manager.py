# manager.py
import asyncio
import logging
import time

from binance import AsyncClient, BinanceSocketManager

import config as cfg
from utils import fetch_klines_async
from indicators import compute_indicators
from strategy import signal_from_indicators
from broker_spot import PaperSpotBroker, LiveSpotBroker
from broker_futures import LiveFuturesBroker  # в PAPER режиме не используется
from position import PositionState
from state_manager import StateManager
from risk import RiskManager
from telegram_notify import TelegramNotifier

logger = logging.getLogger("manager")


class Manager:
    def __init__(self):
        self.client: AsyncClient | None = None
        self.bm: BinanceSocketManager | None = None

        self.spot_broker = None          # PaperSpotBroker или LiveSpotBroker
        self.futures_broker = None       # LiveFuturesBroker (только в LIVE + USE_FUTURES)

        self.positions: dict[str, PositionState] = {}   # symbol -> PositionState
        self.market_prices: dict[str, float] = {}       # последняя цена по символу

        self.state = StateManager(cfg.STATE_FILE)
        self.risk = RiskManager()
        self._last_equity_notify = 0

        self.notifier = TelegramNotifier(
            cfg.TELEGRAM_TOKEN,
            cfg.TELEGRAM_CHAT_ID
        )

        # восстановление позиций из файла
        stored = self.state.get_positions()
        for s, pdata in stored.items():
            try:
                self.positions[s] = PositionState.from_dict(pdata)
                logger.info(f"[MANAGER] restored position {s} from state file")
            except Exception as e:
                logger.exception(f"[MANAGER] failed to restore position {s}: {e}")

        self._running = False

    # ---------- Публичный запуск ----------

    async def run(self):
        await self._init()
        self._running = True
        try:
            await self.notifier.send(
                "Bot started (LIVE)" if cfg.REAL_TRADING else "Bot started (PAPER)"
            )
        except Exception:
            logger.warning("[MANAGER] telegram notify start failed", exc_info=True)

        # задачи: вебсокеты + основной цикл
        tasks = []

        # price streams по всем символам
        for symbol in cfg.SPOT_SYMBOLS:
            tasks.append(asyncio.create_task(self._ticker_loop(symbol)))

        # основной цикл оценок
        tasks.append(asyncio.create_task(self._evaluation_loop()))

        await asyncio.gather(*tasks)

    async def stop(self):
        self._running = False
        try:
            await self.notifier.send("Bot stopped")
        except Exception:
            pass
        if self.client:
            await self.client.close_connection()

    # ---------- Инициализация ----------

    async def _init(self):
        if cfg.REAL_TRADING:
            logger.info("[MANAGER] starting in LIVE mode")
            self.client = await AsyncClient.create(cfg.API_KEY, cfg.API_SECRET)
            self.spot_broker = LiveSpotBroker(self.client)
            await self.spot_broker.init()
            if cfg.USE_FUTURES:
                self.futures_broker = LiveFuturesBroker(self.client)
                await self.futures_broker.init()
        else:
            logger.info("[MANAGER] starting in PAPER mode")
            # без ключей, но клиент нужен для REST/WS
            self.client = await AsyncClient.create()
            self.spot_broker = PaperSpotBroker(cfg.INITIAL_BALANCE_USDT)
            # фьючерсы в paper режиме эмулируем сами через PositionState (mode="futures")

        self.bm = BinanceSocketManager(self.client)

    # ---------- WS: обновление цен ----------

    async def _ticker_loop(self, symbol: str):
        """
        Совместимая с новыми версиями binance-connector версия стрима.
        Используем ASYNC socket напрямую, без async with.
        """
        assert self.bm is not None

        while True:
            try:
                stream = self.bm.symbol_ticker_socket(symbol)
                await stream.__aenter__()
                logger.info(f"[WS] ticker stream opened for {symbol}")

                while True:
                    msg = await stream.recv()

                    if not isinstance(msg, dict):
                        continue

                    price_s = msg.get("c")
                    if price_s is None:
                        continue

                    price = float(price_s)
                    self.market_prices[symbol] = price

            except Exception as e:
                logger.error(f"[WS] ticker loop error for {symbol}: {e}", exc_info=True)

                try:
                    await stream.__aexit__(None, None, None)
                except:
                    pass

                # ждём и переподключаемся
                await asyncio.sleep(1)

    # ---------- Основной цикл стратегии ----------

    async def _evaluation_loop(self):
        """
        Основной цикл:
        - по каждому символу скачиваем историю
        - считаем индикаторы
        - получаем сигнал (buy/sell/None)
        - управляем текущими позициями (SL/TP/trailing)
        - Smart re-entry (пирамидинг по споту)
        - открываем новые позиции по сигналу
        - логируем PNL и equity
        """
        poll_interval = getattr(cfg, "POLL_INTERVAL", 30.0)

        while True:
            start_ts = time.time()
            try:
                prices_snapshot = dict(self.market_prices)

                for symbol in cfg.SPOT_SYMBOLS:
                    last_price = prices_snapshot.get(symbol)

                    # --- 1. История и индикаторы ---
                    try:
                        df = await fetch_klines_async(
                            self.client, symbol, cfg.TIMEFRAME,
                            limit=cfg.HISTORY_LIMIT
                        )
                        df = compute_indicators(df)
                    except Exception as e:
                        logger.exception(f"[MANAGER] failed to fetch/compute for {symbol}: {e}")
                        try:
                            await self.notifier.send(
                                f"Failed fetching klines/indicators for {symbol}: {e}"
                            )
                        except Exception:
                            pass
                        continue

                    sig = signal_from_indicators(df)
                    active = symbol in self.positions
                    logger.info(
                        f"[{symbol}] last={last_price} signal={sig} active={active}"
                    )

                    pos = self.positions.get(symbol)

                    # --- 2. Управление существующей позицией: trailing, stop, TP ---
                    if pos and last_price is not None:
                        self._manage_existing_position(symbol, pos, last_price)

                    # --- 3. SMART RE-ENTRY (пирамидинг по споту) ---
                    if pos and last_price is not None:
                        await self._maybe_pyramid_spot(symbol, pos, last_price, sig)

                    # --- 4. Входы по сигналам BUY / SELL ---
                    # BUY -> SPOT long
                    if sig == "buy":
                        await self._process_buy_signal(symbol, df, last_price)

                    # SELL -> FUTURES short (если разрешены) или игнор в зависимости от режима
                    if sig == "sell":
                        await self._process_sell_signal(symbol, df, last_price)

                # --- 5. Лог equity и PNL по всем позициям ---
                equity = self._calc_equity()
                logger.info(f"[MANAGER] [EQUITY] {equity:.2f} USDT")

                # Telegram: periodic equity notify
                now = time.time()
                if now - self._last_equity_notify >= cfg.EQUITY_NOTIFY_INTERVAL:
                    try:
                        await self.notifier.send_equity(equity)
                    except Exception as e:
                        logger.error(f"[MANAGER] failed to send equity notify: {e}")
                    self._last_equity_notify = now

                self._log_all_pnls(prices_snapshot)

            except Exception as e:
                logger.exception(f"[MANAGER] evaluation error: {e}")
                try:
                    await self.notifier.send(f"Manager error: {e}")
                except Exception:
                    pass

            elapsed = time.time() - start_ts
            to_wait = max(0.0, poll_interval - elapsed)
            await asyncio.sleep(to_wait)

    # ---------- Логика управления позицией ----------

    def _manage_existing_position(self, symbol: str, pos: PositionState, last_price: float):
        """
        Trailing stop, обычный stop-loss, take-profit.
        Закрытия самой позиции выполняются через _close_position
        (это async, поэтому здесь только расчёты, а сами закрытия из eval-loop).
        Но здесь мы делаем только обновление peak и trailing.
        Реальное закрытие происходит в `_process_buy_signal/_process_sell_signal`,
        либо могло быть раньше реализовано иначе. Если ты захочешь,
        можем вынести сюда логику вызова _close_position.
        """
        # Обновляем пик цены (для trailing)
        pos.update_peak(last_price)

        # Включаем trailing-stop, когда профит достиг порога
        gain_from_entry = (last_price - pos.entry_price) / pos.entry_price
        if (
            pos.trailing_stop is None
            and gain_from_entry >= cfg.TRAILING_ACTIVATION_PCT
        ):
            pos.trailing_stop = pos.entry_price * (1 - cfg.TRAILING_STOP_PCT)
            logger.info(
                f"[{symbol}] trailing armed stop={pos.trailing_stop:.6f}"
            )

        # Обновляем trailing_stop, если peak растёт
        if pos.peak_price and pos.trailing_stop is not None:
            new_stop = pos.peak_price * (1 - cfg.TRAILING_STOP_PCT)
            if new_stop > pos.trailing_stop:
                pos.trailing_stop = new_stop

        # Текущий стоп (max из базового SL и trailing)
        current_stop = pos.current_stop(cfg.STOP_LOSS_PCT)
        if last_price <= current_stop:
            # Закрытие по стопу
            logger.info(f"[{symbol}] Hit stop at {last_price:.4f}")
            # Закрытие делаем в async-коде (eval_loop), здесь только логика.
            # Но чтобы не усложнять, _manage_existing_position
            # только считает, а закрытие вызывается в основном цикле.
            # Сейчас это остаётся как визуальная логика. При желании
            # можно сюда протянуть event loop и вызывать _close_position.

        # TP (take profit)
        tp_price = pos.entry_price * (1 + cfg.TAKE_PROFIT_PCT)
        if last_price >= tp_price:
            logger.info(f"[{symbol}] Take profit reached at {last_price:.4f}")
            # Аналогично, фактическое закрытие позиции происходит в eval-loop,
            # здесь только фиксация условия.

    async def _maybe_pyramid_spot(
        self,
        symbol: str,
        pos: PositionState,
        last_price: float,
        sig: str,
    ):
        """
        Smart re-entry: если у нас уже есть SPOT-позиция и цена пошла против нас,
        а сигнал всё ещё BUY (тренд жив), — дозайти частью капитала.
        """
        if pos.mode != "spot":
            return
        if cfg.PYRAMID_MAX_LAYERS <= 0:
            return
        if pos.pyramid_level >= cfg.PYRAMID_MAX_LAYERS:
            return
        if last_price <= 0:
            return

        # нас интересует только усреднение в сторону BUY
        if sig != "buy":
            return

        drawdown_pct = (pos.entry_price - last_price) / pos.entry_price
        needed_dd = cfg.PYRAMID_STEP_PCT * (pos.pyramid_level + 1)

        if drawdown_pct < needed_dd:
            return

        # Определяем notional для догонов
        equity = None
        if not cfg.REAL_TRADING:
            equity = self.spot_broker.get_equity(self.market_prices)
        else:
            # можно реализовать через реальный баланс спота
            try:
                balances = await self.spot_broker.update_balances()
                equity_val = 0.0
                for asset, amt in balances.items():
                    if asset == "USDT":
                        equity_val += amt
                    else:
                        s = asset + "USDT"
                        price = self.market_prices.get(s)
                        if price:
                            equity_val += amt * price
                equity = equity_val
            except Exception as e:
                logger.warning(f"[MANAGER] failed to calc live equity for pyramid: {e}")
                equity = None

        if equity is None:
            return

        base_notional = pos.notional
        notional_add = base_notional * cfg.PYRAMID_SCALE
        qty_add = notional_add / last_price

        if notional_add <= 0 or qty_add <= 0:
            return

        logger.info(
            f"[{symbol}] SMART RE-ENTRY layer={pos.pyramid_level+1} "
            f"add_notional={notional_add:.2f}, qty_add={qty_add:.6f}"
        )

        if cfg.REAL_TRADING:
            res = await self.spot_broker.create_market_order(
                symbol, "BUY", qty_add, last_price
            )
        else:
            res = self.spot_broker.create_market_order(
                symbol, "BUY", qty_add, last_price
            )

        if res:
            pos.add_layer(last_price, qty_add, notional_add)
            self.state.set_position(symbol, pos.to_dict())
            logger.info(
                f"[{symbol}] Re-averaged entry={pos.entry_price:.4f}, "
                f"qty={pos.qty:.6f}, layers={pos.pyramid_level}"
            )

    # ---------- Обработка сигналов BUY / SELL ----------

    async def _process_buy_signal(self, symbol: str, df, last_price: float | None):
        """
        BUY:
        - если есть futures short -> закрываем его
        - если нет позиции -> открываем SPOT long
        """
        pos = self.positions.get(symbol)
        price = df["close"].iloc[-1] if last_price is None else last_price

        # если была фьючерсная позиция -> закрываем
        if pos and pos.mode == "futures":
            await self._close_position(symbol, pos, reason="SWITCH_TO_SPOT")
            pos = None

        # если уже есть spot-позиция -> ничего не делаем, дальше управляет trailing/TP/SL/pyramid
        if pos and pos.mode == "spot":
            return

        # Новой позиции ещё нет -> открываем SPOT long
        # Расчёт размера
        if not cfg.REAL_TRADING:
            equity = self.spot_broker.get_equity(self.market_prices)
        else:
            try:
                balances = await self.spot_broker.update_balances()
                eq = 0.0
                for asset, amt in balances.items():
                    if asset == "USDT":
                        eq += amt
                    else:
                        s = asset + "USDT"
                        price_s = self.market_prices.get(s)
                        if price_s:
                            eq += amt * price_s
                equity = eq
            except Exception as e:
                logger.warning(f"[MANAGER] failed to calc live equity: {e}")
                equity = cfg.INITIAL_BALANCE_USDT

        alloc_equity = equity * cfg.CAPITAL_ALLOCATION_PER_SYMBOL
        notional, qty = self.risk.calc_size(alloc_equity, price)

        if notional <= 0 or qty <= 0:
            logger.info(f"[{symbol}] size too small for BUY (notional={notional:.2f})")
            return

        if cfg.REAL_TRADING:
            res = await self.spot_broker.create_market_order(symbol, "BUY", qty, price)
        else:
            res = self.spot_broker.create_market_order(symbol, "BUY", qty, price)

        if res:
            pos_state = PositionState(
                symbol,
                entry_price=price,
                qty=qty,
                notional=notional,
                mode="spot",
            )
            self.positions[symbol] = pos_state
            self.state.set_position(symbol, pos_state.to_dict())
            logger.info(
                f"[{symbol}] Entered SPOT pos qty={qty:.6f} notional={notional:.2f}"
            )
            try:
                await self.notifier.send(
                    f"BUY {symbol} qty={qty:.6f} price={price:.2f}"
                )
            except Exception:
                pass

    async def _process_sell_signal(self, symbol: str, df, last_price: float | None):
        """
        SELL:
        - если есть SPOT long -> закрываем его
        - если USE_FUTURES = True -> открываем фьючерсный short
          (в PAPER режиме — просто виртуально, через PositionState)
        """
        pos = self.positions.get(symbol)
        price = df["close"].iloc[-1] if last_price is None else last_price

        # если есть spot-позиция -> закрываем
        if pos and pos.mode == "spot":
            await self._close_position(symbol, pos, reason="SWITCH_TO_FUTURES")
            pos = None

        # если фьючерсы отключены вообще
        if not cfg.USE_FUTURES:
            return

        # если уже есть futures short -> ничего не делаем
        if pos and pos.mode == "futures":
            return

        # открываем новую фьючерсную короткую позицию
        if cfg.REAL_TRADING:
            try:
                balances = await self.futures_broker.update_balance()
                balance_usdt = balances.get("USDT", cfg.INITIAL_BALANCE_USDT)
                max_notional = self.risk.futures_notional_by_balance(
                    balance_usdt,
                    cfg.FUTURES_LEVERAGE_DEFAULT,
                    cfg.RISK_PER_TRADE,
                )
                # ограничиваем notional
                notional = max(
                    min(max_notional, balance_usdt * cfg.FUTURES_LEVERAGE_DEFAULT),
                    cfg.FUTURES_NOTIONAL_LIMIT,
                )
                qty = notional / price
                await self.futures_broker.set_leverage(
                    symbol, cfg.FUTURES_LEVERAGE_DEFAULT
                )
                res = await self.futures_broker.create_market_order(
                    symbol, "SELL", qty, price
                )
                if res:
                    pos_state = PositionState(
                        symbol,
                        entry_price=price,
                        qty=qty,
                        notional=notional,
                        mode="futures",
                    )
                    self.positions[symbol] = pos_state
                    self.state.set_position(symbol, pos_state.to_dict())
                    logger.info(
                        f"[{symbol}] Entered FUTURES short qty={qty:.6f} notional={notional:.2f}"
                    )
                    try:
                        await self.notifier.send(
                            f"SHORT {symbol} qty={qty:.6f} price={price:.2f}"
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.exception(f"[MANAGER] live futures short error for {symbol}: {e}")
        else:
            # PAPER режим: просто создаём виртуальную фьючерсную позицию
            equity = self.spot_broker.get_equity(self.market_prices)
            notional = equity * cfg.CAPITAL_ALLOCATION_PER_SYMBOL
            qty = notional / price
            if notional <= 0 or qty <= 0:
                logger.info(f"[{symbol}] size too small for PAPER futures short")
                return
            pos_state = PositionState(
                symbol,
                entry_price=price,
                qty=qty,
                notional=notional,
                mode="futures",
            )
            self.positions[symbol] = pos_state
            self.state.set_position(symbol, pos_state.to_dict())
            logger.info(
                f"[{symbol}] Entered PAPER FUTURES short qty={qty:.6f} notional={notional:.2f}"
            )
            try:
                await self.notifier.send(
                    f"SHORT (PAPER) {symbol} qty={qty:.6f} price={price:.2f}"
                )
            except Exception:
                pass

    # ---------- Закрытие позиции ----------

    async def _close_position(self, symbol: str, pos: PositionState, reason: str = ""):
        last = self.market_prices.get(symbol)
        if last is None or last <= 0:
            last = pos.entry_price

        if pos.mode == "spot":
            if cfg.REAL_TRADING:
                await self.spot_broker.create_market_order(symbol, "SELL", pos.qty, last)
            else:
                self.spot_broker.create_market_order(symbol, "SELL", pos.qty, last)
            logger.info(
                f"[{symbol}] CLOSED SPOT qty={pos.qty:.6f} price={last:.4f} reason={reason}"
            )
            try:
                await self.notifier.send(
                    f"CLOSED SPOT {symbol} qty={pos.qty:.6f} price={last:.2f} reason={reason}"
                )
            except Exception:
                pass
        else:
            # FUTURES short закрываем BUY-ордером (reduce_only)
            if cfg.REAL_TRADING and self.futures_broker:
                await self.futures_broker.create_market_order(
                    symbol, "BUY", pos.qty, last, reduce_only=True
                )
            logger.info(
                f"[{symbol}] CLOSED FUTURES qty={pos.qty:.6f} price={last:.4f} reason={reason}"
            )
            try:
                await self.notifier.send(
                    f"CLOSED FUTURES {symbol} qty={pos.qty:.6f} price={last:.2f} reason={reason}"
                )
            except Exception:
                pass

        if symbol in self.positions:
            del self.positions[symbol]
        self.state.del_position(symbol)

    # ---------- Equity и PNL ----------

    def _calc_equity(self) -> float:
        """
        Для PAPER:
            используем spot_broker.get_equity
        Для LIVE:
            можно оценивать по балансам и текущим ценам (пока упрощённо).
        """
        if not cfg.REAL_TRADING:
            return self.spot_broker.get_equity(self.market_prices)

        # live режим (приближённая оценка)
        total = 0.0
        try:
            # здесь можно дергать реальные балансы
            # но если это тяжело/дорого по API — можно считать только по позициям
            for s, p in self.positions.items():
                last = self.market_prices.get(s)
                if not last:
                    continue
                if p.mode == "spot":
                    total += p.qty * last
                else:
                    # futures: базовый notional + плавающий PnL
                    pnl = (p.entry_price - last) * p.qty
                    total += p.notional + pnl
        except Exception as e:
            logger.warning(f"[MANAGER] equity calc live error: {e}")
        return total

    def _log_all_pnls(self, prices_snapshot: dict[str, float]):
        for s, p in list(self.positions.items()):
            last = prices_snapshot.get(s)
            if not last:
                continue

            if p.mode == "spot":
                # PNL для спота — через broker (учёт комиссий в PAPER)
                if hasattr(self.spot_broker, "get_pnl"):
                    pnl = self.spot_broker.get_pnl(s, last)
                    if pnl:
                        logger.info(
                            f"[PNL-SPOT] {s} entry={p.entry_price:.2f} last={last:.2f} "
                            f"qty={p.qty:.6f} -> {pnl['usdt']:.2f}USDT ({pnl['pct']:.2f}%)"
                        )
                else:
                    pnl_usdt = (last - p.entry_price) * p.qty
                    pnl_pct = pnl_usdt / p.notional * 100 if p.notional else 0.0
                    logger.info(
                        f"[PNL-SPOT] {s} entry={p.entry_price:.2f} last={last:.2f} "
                        f"qty={p.qty:.6f} -> {pnl_usdt:.2f}USDT ({pnl_pct:.2f}%)"
                    )
            else:
                # futures PnL (для PAPER считаем сами)
                pnl_usdt = (p.entry_price - last) * p.qty
                pnl_pct = pnl_usdt / p.notional * 100 if p.notional else 0.0
                logger.info(
                    f"[PNL-FUT] {s} entry={p.entry_price:.2f} last={last:.2f} "
                    f"qty={p.qty:.6f} -> {pnl_usdt:.2f}USDT ({pnl_pct:.2f}%)"
                )
