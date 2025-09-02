from flask import Flask, jsonify
import requests
import pandas as pd
from datetime import datetime, timedelta
import time, threading

app = Flask(__name__)

# Инструменты — тикеры MOEX
INSTRUMENTS = {
    "Сбербанк": "SBER",
    "Газпром": "GAZP",
    "Лукойл": "LKOH",
    "Яндекс": "YNDX",
}

# интервалы: 1 → минута, 60 → час
TIMEFRAMES = {
    "5m": 1,
    "1h": 60,
}

LOOKBACK_DAYS = {
    "5m": 1,
    "1h": 30,
}

CACHE = {}

# ---- функции ----
def fetch_moex_candles(ticker, interval, days):
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"from": start, "interval": interval}
    r = requests.get(url, params=params)
    data = r.json()

    columns = data["candles"]["columns"]
    df = pd.DataFrame(data["candles"]["data"], columns=columns)

    if df.empty:
        return pd.DataFrame()

    df["begin"] = pd.to_datetime(df["begin"])
    return df

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def build_rsi_row_for_instrument(ticker):
    result = {}
    for tf_name, interval in TIMEFRAMES.items():
        df = fetch_moex_candles(ticker, interval, LOOKBACK_DAYS[tf_name])
        if df.empty:
            result[tf_name] = {"RSI": "-", "time": "-"}
            continue

        if tf_name == "5m":
            # агрегируем из минутных свечей
            df = df.iloc[::5, :].reset_index(drop=True)

        df["RSI"] = calc_rsi(df["close"])
        last = df.iloc[-1]
        result[tf_name] = {
            "RSI": round(last["RSI"], 2) if pd.notna(last["RSI"]) else "-",
            "time": last["begin"].strftime("%Y-%m-%d %H:%M"),
        }
    return result

def refresh_cache():
    global CACHE
    while True:
        results = {}
        for name, ticker in INSTRUMENTS.items():
            try:
                results[name] = build_rsi_row_for_instrument(ticker)
            except Exception as e:
                results[name] = {"5m": {"RSI": "-", "time": "-"}, "1h": {"RSI": "-", "time": "-"}}
                print(f"Ошибка для {name}: {e}")
        CACHE = results
        print(f"[{datetime.now()}] Кэш обновлён")
        time.sleep(60)  # обновляем каждую минуту

@app.route("/api/rsi")
def api_rsi():
    return jsonify(CACHE)

if __name__ == "__main__":
    t = threading.Thread(target=refresh_cache, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000)
