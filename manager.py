# manager.py
import asyncio, logging, time
from typing import Dict
import config as cfg
from binance import AsyncClient, BinanceSocketManager
from utils import fetch_klines_async
from strategy import compute_indicators, signal_from_indicators, should_pyramid
from broker_spot import PaperSpotBroker, LiveSpotBroker
from broker_futures import LiveFuturesBroker
from risk import RiskManager
from position import PositionState
from state_manager import StateManager
from telegram_notify import TelegramNotifier

logger = logging.getLogger(__name__)

class Manager:
    def __init__(self):
        self.client = None
        self.spot_broker = None
        self.futures_broker = None
        self.positions: Dict[str, PositionState] = {}
        self.market_prices: Dict[str, float] = {}
        self.risk = RiskManager()
        self.state = StateManager(cfg.STATE_FILE)
        for s, p in self.state.get_positions().items():
            try:
                self.positions[s] = PositionState.from_dict(p)
            except Exception:
                logger.exception(f"[MANAGER] failed to restore position for {s}")
        self.notifier = TelegramNotifier(cfg.TELEGRAM_TOKEN, cfg.TELEGRAM_CHAT_ID)
        self._last_equity_notify = 0
        self._last_trade_time = {}

    async def init(self):
        if cfg.REAL_TRADING:
            self.client = await AsyncClient.create(cfg.API_KEY, cfg.API_SECRET)
            self.spot_broker = LiveSpotBroker(self.client)
            self.futures_broker = LiveFuturesBroker(self.client)
            await self.spot_broker.init()
            await self.futures_broker.init()
            logger.info("[MANAGER] Live brokers initialized")
        else:
            self.client = await AsyncClient.create()
            self.spot_broker = PaperSpotBroker(cfg.INITIAL_BALANCE_USDT)
            self.futures_broker = None
            logger.info("[MANAGER] Paper mode initialized")
        try:
            await self.notifier.send("Bot started (LIVE)" if cfg.REAL_TRADING else "Bot started (PAPER)")
        except Exception:
            pass

    async def start(self):
        await self.init()
        bm = BinanceSocketManager(self.client)
        tasks = []
        for s in cfg.SPOT_SYMBOLS:
            tasks.append(asyncio.create_task(self._ticker_listener(s, bm)))
        tasks.append(asyncio.create_task(self._evaluation_loop()))
        await asyncio.gather(*tasks)

    async def _ticker_listener(self, symbol: str, bm: BinanceSocketManager):
        try:
            async with bm.symbol_ticker_socket(symbol) as stream:
                logger.info(f"[WS] Ticker stream opened for {symbol}")
                while True:
                    try:
                        msg = await stream.recv()
                        if not isinstance(msg, dict):
                            continue
                        price_s = msg.get("c")
                        if price_s is None:
                            continue
                        try:
                            price = float(price_s)
                        except Exception:
                            continue
                        self.market_prices[symbol] = price
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.exception(f"[WS] Error in ticker recv {symbol}: {e}")
                        try:
                            await self.notifier.send(f"WebSocket error for {symbol}: {e}")
                        except Exception:
                            pass
                        await asyncio.sleep(1)
        except Exception as e:
            logger.exception(f"[WS] failed to open ticker for {symbol}: {e}")
            try:
                await self.notifier.send(f"WebSocket failed to open for {symbol}: {e}")
            except Exception:
                pass

    def _can_trade_symbol(self, symbol: str) -> bool:
        now = time.time()
        last = self._last_trade_time.get(symbol, 0)
        if now - last < cfg.COOLDOWN_SECS:
            return False
        if self.state.get_trade_count(symbol) >= cfg.MAX_DAILY_TRADES_PER_SYMBOL:
            return False
        return True

    def _record_trade(self, symbol: str):
        self._last_trade_time[symbol] = time.time()
        self.state.incr_trade_count(symbol)

    async def _evaluation_loop(self):
        while True:
            start = time.time()
            try:
                mp = dict(self.market_prices)
                for symbol in cfg.SPOT_SYMBOLS:
                    last_price = mp.get(symbol)
                    try:
                        df = await fetch_klines_async(self.client, symbol, cfg.TIMEFRAME, limit=cfg.HISTORY_LIMIT)
                        df = compute_indicators(df)
                    except Exception as e:
                        logger.exception(f"[MANAGER] failed to fetch klines for {symbol}: {e}")
                        try:
                            await self.notifier.send(f"Failed fetching klines for {symbol}: {e}")
                        except Exception:
                            pass
                        continue

                    sig = signal_from_indicators(df)
                    logger.info(f"[{symbol}] last={last_price} signal={sig} active={symbol in self.positions}")

                    pos = self.positions.get(symbol)

                    # manage existing pos: update peaks, trailing, tp/sl
                    if pos and last_price:
                        pos.update_peak(float(last_price))
                        if pos.trailing_stop is None and (float(last_price) - pos.entry_price) / pos.entry_price >= cfg.TRAILING_ACTIVATION_PCT:
                            pos.trailing_stop = pos.entry_price * (1 - cfg.TRAILING_STOP_PCT)
                            logger.info(f"[{symbol}] trailing armed stop={pos.trailing_stop:.6f}")
                        if pos.peak_price and pos.trailing_stop is not None:
                            new_stop = pos.peak_price * (1 - cfg.TRAILING_STOP_PCT)
                            if new_stop > pos.trailing_stop:
                                pos.trailing_stop = new_stop
                        current_stop = pos.current_stop(cfg.STOP_LOSS_PCT)
                        if last_price and last_price <= current_stop:
                            logger.info(f"[{symbol}] Hit stop at {last_price:.2f} -> close")
                            await self._close_position(symbol, pos, reason="STOP")
                            continue
                        tp_price = pos.entry_price * (1 + cfg.TAKE_PROFIT_PCT)
                        if last_price and last_price >= tp_price:
                            logger.info(f"[{symbol}] Take profit reached at {last_price:.2f} -> close")
                            await self._close_position(symbol, pos, reason="TP")
                            continue

                    # signal pre-filters
                    if sig in ("buy","sell"):
                        prev_price = df["close"].iloc[-2]
                        if prev_price and last_price:
                            move = abs(last_price - prev_price) / prev_price
                            if move < cfg.MIN_PRICE_MOVE_PCT:
                                logger.info(f"[{symbol}] price move {move:.6f} < MIN_PRICE_MOVE_PCT, skipping signal {sig}")
                                continue
                        if not self._can_trade_symbol(symbol):
                            logger.info(f"[{symbol}] in cooldown or trade limit reached, skipping signal {sig}")
                            continue

                    # BUY flow
                    if sig == "buy":
                        if pos and pos.mode == "spot":
                            # optionally pyramid
                            if should_pyramid(pos, last_price):
                                entry_price = float(df["close"].iloc[-1])
                                notional, qty = self.risk.calc_size(self.spot_broker.get_equity(mp), entry_price)
                                if qty > 0:
                                    res = self.spot_broker.create_market_order(symbol, "BUY", qty, entry_price)
                                    if res:
                                        pos.qty += qty
                                        pos.levels += 1
                                        pos.notional += notional
                                        self.state.set_position(symbol, pos.to_dict())
                                        logger.info(f"[{symbol}] Pyramid BUY added qty={qty:.6f}")
                            continue
                        if pos and pos.mode == "futures":
                            await self._close_position(symbol, pos, reason="SWITCH_TO_SPOT")
                            pos = None
                        if not pos:
                            equity = self.spot_broker.get_equity(mp) if not cfg.REAL_TRADING else None
                            if cfg.REAL_TRADING:
                                try:
                                    balances = await self.spot_broker.update_balances()
                                    equity = 0.0
                                    for a, amt in balances.items():
                                        if a == "USDT":
                                            equity += amt
                                        else:
                                            s = a + "USDT"
                                            if s in mp:
                                                equity += amt * mp[s]
                                except Exception:
                                    equity = cfg.INITIAL_BALANCE_USDT
                            else:
                                equity = self.spot_broker.get_equity(mp)
                            alloc_equity = (equity or cfg.INITIAL_BALANCE_USDT) * cfg.CAPITAL_ALLOCATION_PER_SYMBOL
                            entry_price = float(df["close"].iloc[-1])
                            notional, qty = self.risk.calc_size(alloc_equity, entry_price)
                            if notional <= 0 or qty <= 0:
                                logger.info(f"[{symbol}] size too small (notional={notional:.2f}), skipping")
                            else:
                                if cfg.REAL_TRADING:
                                    res = await self.spot_broker.create_market_order(symbol, "BUY", qty, entry_price)
                                else:
                                    res = self.spot_broker.create_market_order(symbol, "BUY", qty, entry_price)
                                if res:
                                    pos_state = PositionState(symbol, entry_price, qty, notional, mode="spot")
                                    self.positions[symbol] = pos_state
                                    self.state.set_position(symbol, pos_state.to_dict())
                                    self._record_trade(symbol)
                                    logger.info(f"[{symbol}] Entered SPOT pos qty={qty:.8f} notional={notional:.2f}")
                                    try:
                                        await self.notifier.send(f"BUY {symbol} qty={qty:.6f} price={entry_price:.2f}")
                                    except Exception:
                                        pass

                    # SELL flow (open futures short in live or simulate)
                    if sig == "sell":
                        if pos and pos.mode == "spot":
                            await self._close_position(symbol, pos, reason="SWITCH_TO_FUTURES")
                            pos = None
                        if not pos:
                            entry_price = float(df["close"].iloc[-1])
                            if cfg.REAL_TRADING and self.futures_broker:
                                try:
                                    balances = await self.futures_broker.update_balance()
                                except Exception:
                                    balances = {"USDT": cfg.INITIAL_BALANCE_USDT}
                                balance_usdt = balances.get("USDT", cfg.INITIAL_BALANCE_USDT)
                                max_notional = self.risk.futures_notional_by_balance(balance_usdt, cfg.FUTURES_LEVERAGE_DEFAULT, cfg.RISK_PER_TRADE)
                                notional = max(min(max_notional, balance_usdt * cfg.FUTURES_LEVERAGE_DEFAULT), cfg.FUTURES_NOTIONAL_LIMIT)
                                qty = notional / entry_price if entry_price > 0 else 0.0
                                try:
                                    await self.futures_broker.set_leverage(symbol, cfg.FUTURES_LEVERAGE_DEFAULT)
                                except Exception:
                                    pass
                                try:
                                    res = await self.futures_broker.create_market_order(symbol, "SELL", qty, entry_price)
                                except Exception as e:
                                    logger.exception(f"[{symbol}] futures sell failed: {e}")
                                    res = None
                                if res:
                                    pos_state = PositionState(symbol, entry_price, qty, notional, mode="futures")
                                    self.positions[symbol] = pos_state
                                    self.state.set_position(symbol, pos_state.to_dict())
                                    self._record_trade(symbol)
                                    logger.info(f"[{symbol}] Entered FUTURES short qty={qty:.8f} notional={notional:.2f}")
                                    try:
                                        await self.notifier.send(f"SHORT {symbol} qty={qty:.6f} price={entry_price:.2f}")
                                    except Exception:
                                        pass
                            else:
                                equity = self.spot_broker.get_equity(mp)
                                notional = equity * cfg.CAPITAL_ALLOCATION_PER_SYMBOL
                                qty = notional / entry_price if entry_price > 0 else 0.0
                                pos_state = PositionState(symbol, entry_price, qty, notional, mode="futures")
                                self.positions[symbol] = pos_state
                                self.state.set_position(symbol, pos_state.to_dict())
                                self._record_trade(symbol)
                                logger.info(f"[{symbol}] Entered PAPER FUTURES short qty={qty:.8f} notional={notional:.2f}")
                                try:
                                    await self.notifier.send(f"SHORT (PAPER) {symbol} qty={qty:.6f} price={entry_price:.2f}")
                                except Exception:
                                    pass

                # periodic equity notify
                if cfg.TELEGRAM_EQUITY_INTERVAL_MIN > 0:
                    now = time.time()
                    if now - self._last_equity_notify >= cfg.TELEGRAM_EQUITY_INTERVAL_MIN * 60:
                        eq = None
                        if not cfg.REAL_TRADING:
                            try:
                                eq = self.spot_broker.get_equity(mp)
                            except Exception:
                                eq = None
                        else:
                            try:
                                balances = await self.spot_broker.update_balances()
                                eq = 0.0
                                for a, amt in balances.items():
                                    if a == "USDT":
                                        eq += amt
                                    else:
                                        s = a + "USDT"
                                        if s in mp:
                                            eq += amt * mp[s]
                            except Exception:
                                eq = None
                        if eq is not None:
                            try:
                                await self.notifier.send(f"Equity update: {eq:.2f} USDT")
                            except Exception:
                                pass
                            self._last_equity_notify = now

                # PnL logging
                for s, p in list(self.positions.items()):
                    last = mp.get(s)
                    if last:
                        if p.mode == "spot":
                            pnl = None
                            if hasattr(self.spot_broker, "get_pnl"):
                                try:
                                    pnl = self.spot_broker.get_pnl(s, float(last))
                                except Exception as e:
                                    logger.exception(f"[MANAGER] spot get_pnl error for {s}: {e}")
                            if pnl:
                                try:
                                    logger.info(f"[PNL] {s} entry={p.entry_price:.2f} last={last:.2f} qty={p.qty:.6f} -> {pnl['usdt']:.2f}USDT ({pnl['pct']:.2f}%)")
                                except Exception:
                                    logger.info(f"[PNL] {s} pnl: {pnl}")
                        else:
                            if not cfg.REAL_TRADING:
                                try:
                                    pnl_usdt = (p.entry_price - float(last)) * p.qty
                                    pnl_pct = pnl_usdt / p.notional * 100 if p.notional else 0.0
                                    logger.info(f"[PNL-FUT] {s} entry={p.entry_price:.2f} last={last:.2f} qty={p.qty:.6f} -> {pnl_usdt:.2f}USDT ({pnl_pct:.2f}%)")
                                except Exception:
                                    logger.exception(f"[MANAGER] pnl-fut calc failed for {s}")

            except Exception as e:
                logger.exception(f"[MANAGER] evaluation error: {e}")
                try:
                    await self.notifier.send(f"Manager error: {e}")
                except Exception:
                    pass

            elapsed = time.time() - start
            to_wait = max(0.0, cfg.POLL_INTERVAL - elapsed)
            await asyncio.sleep(to_wait)

    async def _close_position(self, symbol: str, pos: PositionState, reason: str = ""):
        last = self.market_prices.get(symbol)
        if last is None:
            try:
                df = await fetch_klines_async(self.client, symbol, cfg.TIMEFRAME, limit=2)
                last = float(df["close"].iloc[-1])
            except Exception:
                last = None

        if pos.mode == "spot":
            try:
                if cfg.REAL_TRADING:
                    await self.spot_broker.create_market_order(symbol, "SELL", pos.qty, last)
                else:
                    self.spot_broker.create_market_order(symbol, "SELL", pos.qty, last)
                try:
                    await self.notifier.send(f"CLOSED SPOT {symbol} qty={pos.qty:.6f} price={last:.2f} reason={reason}")
                except Exception:
                    pass
            except Exception as e:
                logger.exception(f"[MANAGER] failed to close spot {symbol}: {e}")
        else:
            try:
                if cfg.REAL_TRADING and self.futures_broker:
                    await self.futures_broker.create_market_order(symbol, "BUY", pos.qty, last, reduce_only=True)
                else:
                    pass
                try:
                    await self.notifier.send(f"CLOSED FUTURES {symbol} qty={pos.qty:.6f} price={last:.2f} reason={reason}")
                except Exception:
                    pass
            except Exception as e:
                logger.exception(f"[MANAGER] failed to close futures {symbol}: {e}")

        if symbol in self.positions:
            try:
                del self.positions[symbol]
            except Exception:
                self.positions.pop(symbol, None)
        try:
            self.state.del_position(symbol)
        except Exception:
            logger.exception(f"[MANAGER] state.del_position failed for {symbol}")

        try:
            if not cfg.REAL_TRADING:
                eq = self.spot_broker.get_equity(self.market_prices)
                self.state.set_equity(eq)
        except Exception:
            pass

    async def stop(self):
        try:
            await self.notifier.send("Bot stopped")
        except Exception:
            pass
        try:
            await self.notifier.close()
        except Exception:
            pass
