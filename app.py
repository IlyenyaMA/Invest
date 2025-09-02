from flask import Flask, jsonify, send_from_directory
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta, timezone
import pandas as pd
import threading
import time

# 🔑 Вставь сюда свой токен Tinkoff API
TOKEN = "t.a_yTo2QKdKX0FFwrNTmkvlKAfBml74hg7SVdW-GbyAVhY5znKubj2meA61ufoYGu_awUxQvozh07QHBrY3OgZA"


# Популярные FIGI для теста
INSTRUMENTS = {
    "Сбербанк": "BBG004730N88",
    "Газпром": "BBG004730RP0",
    "Лукойл": "BBG004731354",
    "Яндекс": "BBG006L8G4H1",
}

app = Flask(__name__, static_folder="static")
CACHE = {}  # кэш для актуальных данных

# ===== Функция расчёта RSI =====
def compute_rsi(prices: pd.Series, period: int = 14) -> float:
    delta = prices.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.rolling(period).mean()
    roll_down = down.rolling(period).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)

# ===== Получение свечей и расчёт RSI =====
def fetch_rsi(client, figi: str, interval: CandleInterval) -> dict:
    now = datetime.utcnow()
    days = 10 if interval == CandleInterval.CANDLE_INTERVAL_5_MIN else 60
    from_ = now - timedelta(days=days)

    try:
        resp = client.market_data.get_candles(
            figi=figi,
            from_=from_,
            to=now,
            interval=interval
        )
        candles = resp.candles
        if not candles:
            return {"RSI": "-", "time": "-"}
        prices = pd.Series([c.c for c in candles])
        if len(prices) < 15:
            return {"RSI": "-", "time": "-"}
        rsi_val = compute_rsi(prices)
        last_time = candles[-1].time.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
        return {"RSI": rsi_val, "time": last_time}
    except Exception as e:
        print(f"[ERROR] fetch_rsi {figi}: {e}")
        return {"RSI": "-", "time": "-"}

# ===== Фоновый поток обновления кеша =====
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
            print(f"🔄 Cache updated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(60)  # обновление каждую минуту

# ===== Flask маршруты =====
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/rsi")
def api_rsi():
    return jsonify(CACHE)

if __name__ == "__main__":
    t = threading.Thread(target=refresh_cache, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000)
