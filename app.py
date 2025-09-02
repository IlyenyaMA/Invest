# app.py — Flask backend (Tinkoff Invest API, RSI14)
from flask import Flask, jsonify, send_from_directory
from tinkoff.invest import Client, CandleInterval
import pandas as pd
from datetime import datetime, timedelta, timezone
import threading
import time

app = Flask(__name__, static_folder="static")

# ------------------- НАСТРОЙКИ -------------------
TOKEN = "t.a_yTo2QKdKX0FFwrNTmkvlKAfBml74hg7SVdW-GbyAVhY5znKubj2meA61ufoYGu_awUxQvozh07QHBrY3OgZA"
INSTRUMENTS = {
    "Башнефть": "BBG004S68758",
    "Трубная Металлургическая Компания": "BBG004TC84Z8",
    "Московская Биржа": "BBG004730JJ5",
    "Башнефть — привилегированные акции": "BBG004S686N0",
    "РУСАЛ": "BBG008F2T3T2",
    "Таттелеком": "BBG000RJL816",
    "МРСК Урала": "BBG000VKG4R5",
    "Норильский никель": "BBG004731489",
    "МРСК Северо-Запада": "BBG000TJ6F42",
    "ТГК-2": "BBG000Q7GG57",
    "ПАО «КАЗАНЬОРГСИНТЕЗ»": "BBG0029SFXB3",
    "МОЭСК": "BBG004S687G6",
    "QIWI": "BBG005D1WCQ1",
    
}

TIMEFRAMES = {
    "5m": CandleInterval.CANDLE_INTERVAL_5_MIN,
    "1h": CandleInterval.CANDLE_INTERVAL_HOUR,
}

LOOKBACK_DAYS = {
    "5m": 7,    # последние 7 дней
    "1h": 10,   # последние 10 дней
}

RSI_PERIOD = 14
REFRESH_SECONDS = 60
RSI_CACHE = {}
CACHE_LOCK = threading.Lock()

# ------------------- HELPERS -------------------
def rsi(series, period=RSI_PERIOD):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down
    return 100 - (100 / (1 + rs))

def get_days_for_interval(tf_name):
    return LOOKBACK_DAYS.get(tf_name, 30)

def get_rsi(client, figi, tf_name, interval):
    days = get_days_for_interval(tf_name)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    try:
        candles_resp = client.market_data.get_candles(
            figi=figi,
            from_=start,
            to=now,
            interval=interval
        )
        candles = candles_resp.candles
    except Exception as e:
        print(f"[ERROR] FIGI {figi} ({tf_name}): {e}")
        return None, None

    if not candles or len(candles) < RSI_PERIOD:
        return None, None

    closes = [c.close.units + c.close.nano / 1e9 for c in candles]

    # заменяем последнюю цену на актуальную
    try:
        last_price_resp = client.market_data.get_last_prices(figi=[figi])
        if last_price_resp.last_prices:
            current_price = (
                last_price_resp.last_prices[0].price.units
                + last_price_resp.last_prices[0].price.nano / 1e9
            )
            closes[-1] = current_price
    except Exception as e:
        print(f"[WARN] Не удалось получить last_price для {figi}: {e}")

    rsi_val = round(rsi(pd.Series(closes)).iloc[-1], 2)
    last_time = candles[-1].time.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
    return rsi_val, last_time

# ------------------- Фоновое обновление кэша -------------------
def refresh_cache():
    global RSI_CACHE
    while True:
        new_cache = {}
        with Client(TOKEN) as client:
            for name, figi in INSTRUMENTS.items():
                row = {}
                for tf_name, interval in TIMEFRAMES.items():
                    val, last_time = get_rsi(client, figi, tf_name, interval)
                    if val is not None:
                        row[tf_name] = {"RSI": val, "time": last_time}
                    else:
                        row[tf_name] = {"RSI": "-", "time": "-"}
                new_cache[name] = row
        with CACHE_LOCK:
            RSI_CACHE = new_cache
        print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Cache updated")
        time.sleep(REFRESH_SECONDS)

# ------------------- Маршруты -------------------
@app.route("/api/rsi")
def api_rsi():
    with CACHE_LOCK:
        return jsonify(RSI_CACHE)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

# ------------------- MAIN -------------------
if __name__ == "__main__":
    threading.Thread(target=refresh_cache, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)


