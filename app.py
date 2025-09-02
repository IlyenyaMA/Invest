from flask import Flask, jsonify, send_from_directory
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta, timezone
import pandas as pd
import threading
import time

# 🔑 Ваш токен Tinkoff Invest API
TOKEN = "t.a_yTo2QKdKX0FFwrNTmkvlKAfBml74hg7SVdW-GbyAVhY5znKubj2meA61ufoYGu_awUxQvozh07QHBrY3OgZA"

# FIGI инструментов (пример)
INSTRUMENTS = {
    "Башнефть": "BBG004S68758",
    "Трубная Металлургическая Компания": "BBG004TC84Z8",
    "Московская Биржа": "BBG004730JJ5",
    "Башнефть — привилегированные акции": "BBG004S686N0",
    "РУСАЛ": "BBG008F2T3T2"
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
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=5)  # берем последние 5 дней
    try:
        response = client.market_data.get_candles(
            figi=figi,
            from_=start,
            to=now,
            interval=interval
        )
        candles = response.candles  # здесь список объектов свечей

        if not candles:
            print(f"[WARN] Пустые свечи для FIGI {figi}, interval {interval}")
            return {"RSI": "-", "time": "-"}

        prices = pd.Series([float(c.c) for c in candles])
        rsi_val = compute_rsi(prices)

        last_time = candles[-1].time.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")

        return {"RSI": rsi_val, "time": last_time}

    except Exception as e:
        print(f"[ERROR] fetch_rsi {figi}: {e}")
        return {"RSI": "-", "time": "-"}

# ===== Фоновое обновление кэша =====
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
            time.sleep(60)

# ===== Маршруты =====
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/rsi")
def api_rsi():
    return jsonify(CACHE)

if __name__ == "__main__":
    # фоновый поток для обновления кэша
    t = threading.Thread(target=refresh_cache, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000)


