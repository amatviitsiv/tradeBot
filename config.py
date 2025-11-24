# config.py
"""
Глобальные настройки бота (и для спота, и для фьючерсов).
Эта конфигурация рассчитана на:
- дуальный режим (spot + futures short)
- multi-asset: BTC, ETH, SOL, BNB, AVAX
- paper / real переключение одним флагом
"""

# ===== РЕЖИМ ТОРГОВЛИ =====
# False = paper trading (без реальных ордеров)
# True  = реальная торговля (нужны ключи и аккуратность!)
REAL_TRADING = False

EQUITY_NOTIFY_INTERVAL = 600
# API ключи для Binance (заполняешь ТОЛЬКО если REAL_TRADING = True)
API_KEY = "kpE6FHApowcp7kD0ji3FBrSqFJM674mF5Idm87K8cxRPulLA1NdziRd3rJKTpqa1"
API_SECRET = "fSBKFMPQ2M4DWUGBZhK4xYOvrc7QfKOashAw9eXk6dhLElDh71h4KCe2kYHuVI0c"

# ===== СПИСОК ПАР ДЛЯ ТОРГОВЛИ =====
SPOT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"]

# ===== ТАЙМФРЕЙМ И ИСТОРИЯ =====
# Свечи для расчёта индикаторов
TIMEFRAME = "1m"        # можно потом сменить на "5m"
HISTORY_LIMIT = 300      # сколько свечей тянем для индикаторов

# ===== НАЧАЛЬНЫЙ БАЛАНС (PAPER) =====
INITIAL_BALANCE_USDT = 5000.0

# ===== КОМИССИИ =====
# Комиссия спота (пример: 0.1% = 0.001)
SPOT_FEE_RATE = 0.001
# Комиссия фьючерсов (пример: 0.04% = 0.0004)
FUTURES_FEE_RATE = 0.0004

# ===== УПРАВЛЕНИЕ КАПИТАЛОМ =====
# Доля капитала на одну сделку/символ (для спота и для «виртуального» фьючерса)
CAPITAL_ALLOCATION_PER_SYMBOL = 0.2   # 20% от equity на одну пару
# Риск на сделку (если захочешь считать через стоп)
RISK_PER_TRADE = 0.01                 # 1% от equity

# ===== РИСК-менеджмент (SPOT) =====
# Тейк-профит, стоп-лосс и трейлинг в долях (1% = 0.01)
TAKE_PROFIT_PCT = 0.01          # 1% вверх от входа
STOP_LOSS_PCT = 0.01            # 1% вниз от входа
TRAILING_ACTIVATION_PCT = 0.01  # когда активировать трейлинг (прибыль > 1%)
TRAILING_STOP_PCT = 0.005       # трейлинг-стоп ~0.5% от пика

# ===== ФЬЮЧЕРСЫ =====
# Базовое плечо. В коде можно будет делать dynamic_leverage(equity)
FUTURES_LEVERAGE_DEFAULT = 5
FUTURES_NOTIONAL_LIMIT = 2000.0  # максимальный размер позиции в USDT (для безопасности)

# ===== ЛОГИКА ОПРОСА =====
# Как часто перезапускаем цикл оценки стратегии (в секундах)
POLL_INTERVAL = 30.0

# ===== ФАЙЛ СОСТОЯНИЯ =====
STATE_FILE = "bot_state.json"

# ===== TELEGRAM (опционально) =====
# Если не хочешь телеграм сейчас — можно оставить строки пустыми
TELEGRAM_TOKEN = "8269222363:AAF6vM7-ydXHJjBiq42MDK4jWn5sYbIub7w"
TELEGRAM_CHAT_ID = 351630680

# Раз в сколько минут слать апдейт по equity (0 = выключить)
TELEGRAM_EQUITY_INTERVAL_MIN = 5

# ===== ЛОГИ =====
LOG_LEVEL = "INFO"
LOG_FILE = "bot.log"
TRADES_LOG_FILE = "trades.log"
ERROR_LOG_FILE = "errors.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
# === Trend strategy params (Dual Trend Bot) ===

# EMA для входа по откатам
EMA_FAST = 20
EMA_SLOW = 50

# Долгосрочный тренд-фильтр (бычий/медвежий рынок)
SMA_TREND_PERIOD = 200   # SMA200 по закрытиям

# ATR для оценки волатильности (можно пока не использовать в risk, но считаем)
ATR_PERIOD = 14

# ADX — сила тренда
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 20  # тренд считается сильным, если ADX >= 20

# Ограничение сделок по тренду:
# - buy только если цена > SMA200 и EMA_FAST > EMA_SLOW и ADX >= порога
# - sell только если цена < SMA200 и EMA_FAST < EMA_SLOW и ADX >= порога
# === Anti-chop / trend filters ===

# ADX порог для "сильного тренда"
ADX_TREND_THRESHOLD = 20.0          # было уже, можно поднять до 25–30 если шумно

# Минимальная волатильность (ATR) относительно цены,
# чтобы вообще считать рынок пригодным для входа
ANTI_CHOP_MIN_ATR_PCT = 0.002       # 0.2% от цены, можно играться

# === Smart re-entry (пирамида) ===

# Максимальное количество добавочных входов поверх первой позиции
PYRAMID_MAX_LAYERS = 2              # напр: 0 = отключено, 1–3 = разумно

# На сколько % цена должна уйти против позиции, чтобы сделать ДО-вход
PYRAMID_STEP_PCT = 0.015            # 1.5% против нас -> догон

# Размер каждого добавочного входа относительно исходного notional
PYRAMID_SCALE = 0.5                 # 0.5 = каждый догон на половину первоначального объёма