Spot indicator trading bot — full project

1) Установка
python -m venv venv
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

2) Конфигурация
Открой config.py. По умолчанию REAL_TRADING=False (paper trading).
Укажи SYMBOLS, параметры стратегии и стартовый баланс.

3) Запуск
python main.py

4) Live trading
- Прежде чем включать REAL_TRADING=True:
  * реализуй проверки и убедись, что LIVE API_KEY и API_SECRET верные и не имеют withdraw.
  * протестируй на минимальных суммах.
  * проверь exchangeInfo шаги/тиков для каждой пары.

5) Что делает бот
- Вычисляет EMA / SMA / RSI / MACD.
- Формирует сигналы buy/sell.
- Входит с размером по риск-менеджменту (RISK_PER_TRADE и STOP_LOSS_PCT).
- Поддерживает pyramid и trailing stop.
- В бумажном режиме учитывает taker fee.
