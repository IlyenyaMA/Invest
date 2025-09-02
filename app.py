# app.py — Flask backend, RSI14 с актуальной ценой
from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import threading
import time

app = Flask(__name__, static_folder="static")

TICKERS = {
    "SBER": "SBER",
    "GAZP": "GAZP",
    "LKOH": "LKOH"
}
API_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/securities"

# Кэш для данных
cache = {}


# --- Получение свечей ---
def fetch_candles(ticker: str, interval: int, days: int):
    """
    Забираем свечи через ISS API.
    interval: 1 (1m), 5 (5m), 60 (1h), и т.д.
    days: сколько дней назад загружать
    """
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"{API_URL}/{ticker}/candles.json?from={start}&interval={interval}"
    r = requests.get(url)
    r.raise_for_status()
    data = r.json()

    candles = data.get("candles", {}).get("data", [])
    cols = data.get("candles", {}).get("columns", [])
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles, columns=cols)
    df["end"] = pd.to_datetime(df["end"])
    return df


# --- Получение текущей цены ---
def fetch_last_price(ticker: str) -> float:
    url = f"{API_URL}/{ticker}.json"
    r = requests.get(url)
    r.raise_for_status()
    data = r.json()
    secdata = data.get("securities", {}).get("data", [])
    cols = data.get("securities", {}).get("columns", [])
    if not secdata:
        return None
    df = pd.DataFrame(secdata, columns=cols)
    return float(df.iloc[0]["LAST"])


# --- RSI ---
def compute_rsi(prices: pd.Series, period: int = 14) -> float:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]


# --- Основная логика ---
def fetch_rsi(ticker: str, interval: int, days: int):
    df = fetch_candles(ticker, interval, days)
    if df.empty:
        return None, None

    closes = df["close"].astype(float)

    # Добавляем последнюю цену
    last_price = fetch_last_price(ticker)
    if last_price:
        closes = pd.concat([closes, pd.Series([last_price])], ignore_index=True)

    # RSI по последним 14 значениям
    if len(closes) < 14:
        return None, None

    rsi_value = compute_rsi(closes, period=14)
    # возвращаем текущее московское время
    now_msk = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")

    return round(rsi_value, 2), now_msk


# --- Обновление кэша в фоне ---
def refresh_cache():
    while True:
        new_cache = {}
        for name, ticker in TICKERS.items():
            rsi_5m, t5 = fetch_rsi(ticker, 5, days=7)   # последние 7 дней
            rsi_1h, t1 = fetch_rsi(ticker, 60, days=10) # последние 10 дней
            new_cache[name] = {
                "5m": rsi_5m,
                "5m_time": t5,
                "1h": rsi_1h,
                "1h_time": t1
            }
        global cache
        cache = new_cache
        time.sleep(60)  # обновляем каждую минуту


# --- Маршруты ---
@app.route("/api/rsi")
def get_rsi():
    return jsonify(cache)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# --- Запуск ---
if __name__ == "__main__":
    t = threading.Thread(target=refresh_cache, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000)
