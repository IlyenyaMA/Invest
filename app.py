import os
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, send_from_directory
from tinkoff.invest import Client, CandleInterval
import pandas as pd
import numpy as np

# --- Настройки ---
TOKEN = os.getenv("t.a_yTo2QKdKX0FFwrNTmkvlKAfBml74hg7SVdW-GbyAVhY5znKubj2meA61ufoYGu_awUxQvozh07QHBrY3OgZA")  # ключ из переменной окружения
TZ = timezone.utc

app = Flask(__name__, static_folder="static")

# --- Инструменты (FIGI: Название) ---
INSTRUMENTS = {
    "BBG004730RP0": "Сбербанк",
    "BBG004S68829": "Газпром",
    "BBG004730ZJ9": "Лукойл",
}

# --- Глобальный кэш ---
CACHE = {}


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def calculate_rsi(prices, period: int = 14):
    """Расчёт RSI по ценам (numpy array)."""
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    up_avg, down_avg = up, down
    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        up_val = max(delta, 0)
        down_val = -min(delta, 0)

        up_avg = (up_avg * (period - 1) + up_val) / period
        down_avg = (down_avg * (period - 1) + down_val) / period

        rs = up_avg / down_avg if down_avg != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)

    return rsi[-1]


def fetch_rsi(client: Client, figi: str, interval: CandleInterval, days: int):
    """Загружаем свечи и считаем RSI14, включая актуальную цену."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    candles = client.market_data.get_candles(
        figi=figi,
        from_=start,
        to=now,
        interval=interval,
    ).candles

    if not candles:
        return None, None

    prices = np.array([candle.close.units + candle.close.nano / 1e9 for candle in candles])

    # добавляем актуальную цену (последняя известная котировка)
    last_price = client.market_data.get_last_prices(figi=[figi]).last_prices[0].price
    current_price = last_price.units + last_price.nano / 1e9
    prices = np.append(prices, current_price)

    rsi = calculate_rsi(prices)
    return rsi, now.strftime("%Y-%m-%d %H:%M:%S")


def refresh_cache():
    """Фоновое обновление кеша RSI."""
    with Client(TOKEN) as client:
        while True:
            for name, figi in FIGIS.items():
                try:
                    rsi_5m, time_5m = fetch_rsi(client, figi, CandleInterval.CANDLE_INTERVAL_5_MIN, days=7)
                    rsi_1h, time_1h = fetch_rsi(client, figi, CandleInterval.CANDLE_INTERVAL_HOUR, days=10)

                    CACHE[name] = {
                        "5m": {"rsi": rsi_5m, "time": time_5m},
                        "1h": {"rsi": rsi_1h, "time": time_1h},
                    }
                except Exception as e:
                    print(f"Ошибка при обновлении {name}: {e}")

            time.sleep(60)  # обновляем каждую минуту


@app.route("/api/data")
def get_data():
    return jsonify(CACHE)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    threading.Thread(target=refresh_cache, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)

