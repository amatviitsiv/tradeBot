from fetch_history_binance import fetch_klines
from backtester_full import Backtester
import matplotlib.pyplot as plt

SYMBOL = "BTCUSDT"
TIMEFRAME = "1m"
LIMIT = 1500

df = fetch_klines(SYMBOL, TIMEFRAME, LIMIT)

tester = Backtester(SYMBOL, df)
result = tester.run()

print("=== BACKTEST RESULT ===")
print(result)

plt.plot(tester.equity_curve)
plt.title(f"Equity curve {SYMBOL}")
plt.xlabel("Candle")
plt.ylabel("Equity (USDT)")
plt.show()
