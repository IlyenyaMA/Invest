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

def get_candles(client, figi, start, end, interval):
    """Загружаем свечи"""
    candles = client.market_data.get_candles(
        figi=figi,
        from_=start,
        to=end,
        interval=interval
    )
    return candles.candles


def candles_to_df(candles):
    """Перевод свечей в DataFrame"""
    if not candles:
        return pd.DataFrame()
    data = [{
        "time": c.time.replace(tzinfo=TZ),
        "c": float(c.close.units) + c.close.nano / 1e9
    } for c in candles]
    df = pd.DataFrame(data)
    df.set_index("time", inplace=True)
    return df


def compute_rsi_from_list(prices, period=14):
    """RSI из списка цен"""
    if len(prices) < period + 1:
        return None

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def build_rsi_row_for_instrument(client, figi, name):
    """Формируем строку с RSI для таблицы"""
    try:
        now = datetime.now(TZ)

        # --- 1m свечи для пересчёта в 5m ---
        candles_1m = get_candles(client, figi, now - timedelta(days=7), now, CandleInterval.CANDLE_INTERVAL_1_MIN)
        df_1m = candles_to_df(candles_1m)
        if not df_1m.empty:
            df_5m = df_1m.resample("5T").agg({"c": "last"}).dropna()
            prices_5m = df_5m["c"].tolist()[-14:]
        else:
            prices_5m = []

        # --- часовые свечи ---
        candles_1h = get_candles(client, figi, now - timedelta(days=10), now, CandleInterval.CANDLE_INTERVAL_HOUR)
        df_1h = candles_to_df(candles_1h)
        prices_1h = df_1h["c"].tolist()[-14:] if not df_1h.empty else []

        # --- добавляем актуальную цену ---
        last_price_resp = client.market_data.get_last_prices(figi=[figi])
        if last_price_resp.last_prices:
            lp = last_price_resp.last_prices[0].price
            last_price = float(lp.units) + lp.nano / 1e9
            if prices_5m:
                prices_5m.append(last_price)
            if prices_1h:
                prices_1h.append(last_price)

        # --- считаем RSI ---
        rsi_5m = compute_rsi_from_list(prices_5m)
        rsi_1h = compute_rsi_from_list(prices_1h)

        return {
            "instrument": name,
            "5m": rsi_5m if rsi_5m is not None else "-",
            "1h": rsi_1h if rsi_1h is not None else "-",
            "time": now.strftime("%Y-%m-%d %H:%M:%S")
        }

    except Exception as e:
        print(f"Ошибка для {name}: {e}")
        return {"instrument": name, "5m": "-", "1h": "-", "time": "-"}


# ===== ОБНОВЛЕНИЕ КЭША =====

def refresh_cache():
    global CACHE
    with Client(TOKEN) as client:
        while True:
            rows = []
            for figi, name in INSTRUMENTS.items():
                row = build_rsi_row_for_instrument(client, figi, name)
                rows.append(row)
            CACHE = {"data": rows}
            time.sleep(60)  # обновление раз в минуту


# ===== ROUTES =====

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/data")
def data():
    return jsonify(CACHE)


# ===== MAIN =====

if __name__ == "__main__":
    threading.Thread(target=refresh_cache, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
