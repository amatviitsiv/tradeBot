# utils.py
import aiohttp
import math
import logging
import pandas as pd
import asyncio
import time

import config as cfg


logger = logging.getLogger(__name__)


# ========== ОКРУГЛЕНИЕ ДО ШАГА БИРЖИ ==========

def round_step(value: float, step: float) -> float:
    """
    Округляет значение value к шагу step.
    Пример: step=0.0001 → цена округляется правильно.
    """
    if step <= 0:
        return value
    return math.floor(value / step) * step


def round_down(value: float, decimals: int) -> float:
    """
    Жёсткое округление вниз до decimals знаков.
    """
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


# ========== ПОЛУЧЕНИЕ СВЕЧЕЙ (KLINES) через aiohttp ==========

async def fetch_klines_async(client, symbol: str, interval: str, limit: int = 300):
    """
    Асинхронное получение свечей Binance через официальный клиент AsyncClient.
    Возвращает pandas.DataFrame с float-значениями.
    """
    try:
        raw = await client.get_klines(symbol=symbol, interval=interval, limit=limit)
    except Exception as e:
        logger.exception(f"[UTILS] Error fetching klines {symbol}: {e}")
        raise

    # Преобразуем в DataFrame
    cols = [
        "open_time", "open", "high", "low", "close",
        "volume", "close_time", "quote_av", "trades",
        "tb_base_av", "tb_quote_av", "ignore"
    ]

    df = pd.DataFrame(raw, columns=cols)
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)

    return df


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def calc_notional(price: float, qty: float) -> float:
    """Считает итоговый размер позиции."""
    return price * qty


def safe_float(v):
    """Безопасная конвертация строки/числа в float."""
    try:
        return float(v)
    except:
        return 0.0


async def sleep_corrected(start_time, target_interval):
    """
    Ждём остаток времени так, чтобы цикл работал равномерно.
    """
    elapsed = time.time() - start_time
    to_wait = max(0.0, target_interval - elapsed)
    await asyncio.sleep(to_wait)


# ========== ЛОГИРОВАНИЕ СДЕЛОК В ФАЙЛ ==========
def log_trade(message: str):
    """Запись трейдов в отдельный файл."""
    with open(cfg.TRADES_LOG_FILE, "a") as f:
        f.write(message + "\n")


def log_error(message: str):
    """Запись ошибок в отдельный файл."""
    with open(cfg.ERROR_LOG_FILE, "a") as f:
        f.write(message + "\n")
