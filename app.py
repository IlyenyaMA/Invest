from flask import Flask, jsonify
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta, timezone
import pandas as pd
import time
import threading

# 🔑 твой токен Tinkoff Invest API
TOKEN = "t.a_yTo2QKdKX0FFwrNTmkvlKAfBml74hg7SVdW-GbyAVhY5znKubj2meA61ufoYGu_awUxQvozh07QHBrY3OgZA"

# FIGI для инструментов (пример)
INSTRUMENTS = {
    "SBER": "BBG004730N88",
    "GAZP": "BBG004730RP0",
    "LKOH": "BBG004731354",
    "YNDX": "BBG006L8G4H1",
}

app = Flask(__name__)

CACHE = {}  # сюда складываем данные

# 🔹 функция расчёта RSI
def compute_rsi(prices: pd.Series, period: int = 14) -> float:
    delta = prices.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.rolling(period).mean()
    roll_down = down.rolling(period).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)

# 🔹 достаём свечи для FIGI
def fetch_rsi(client, figi: str, interval: CandleInterval, depth: int = 100) -> dict:
    now = datetime.now(timezone.utc)
    candles = client.get_market_candles(
        figi=figi,
        from_=now - timedelta(days=5),
        to=now,
        interval=interval,
    ).candles

    if not candles:
        return {"RSI": None, "time": None}

    prices = pd.Series([float(c.c) for c in candles])
    rsi_val = compute_rsi(prices)

    return {
        "RSI": rsi_val,
        "time": candles[-1].time.isoformat()
    }

# 🔹 фоновое обновление кэша
def refresh_cache():
    global CACHE
    with Client(TOKEN) as client:
        while True:
            results = {}
            for name, figi in INSTRUMENTS.items():
                results[name] = {
                    "5m": fetch_rsi(client, figi, CandleInterval.CANDLE_INTERVAL_5_MIN),
                    "1h": fetch_rsi(client, figi, CandleInterval.CANDLE_INTERVAL_HOUR),
                }
            CACHE = results
            print("🔄 Cache updated", datetime.now())
            time.sleep(60)  # обновляем раз в минуту

@app.route("/api/rsi")
def api_rsi():
    return jsonify(CACHE)

if __name__ == "__main__":
    t = threading.Thread(target=refresh_cache, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000)
