# app.py — Flask backend, RSI14 с актуальной ценой
from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import threading
import time

app = Flask(__name__, static_folder="static")

INSTRUMENTS = {
    "Сбербанк": "SBER",
    "Газпром": "GAZP",
    "Лукойл": "LKOH",
    "Яндекс": "YNDX",
}

LOOKBACK_DAYS = {
    "5m": 7,
    "1h": 10,
}

RSI_CACHE = {}
CACHE_LOCK = threading.Lock()
RSI_PERIOD = 14  # период RSI

# --- Получение свечей ---
def fetch_moex_candles(ticker: str, interval: str, days: int):
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
    now = datetime.utcnow()
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    params = {"from": start, "till": end, "interval": interval}
    try:
        r = requests.get(url, params=params, timeout=12)
        r.raise_for_status()
        payload = r.json()
        candles = payload.get("candles", {})
        cols = candles.get("columns", [])
        rows = candles.get("data", [])
        if not rows or not cols:
            return None
        return pd.DataFrame(rows, columns=cols)
    except Exception as e:
        print(f"[ISS] error fetching candles for {ticker} interval={interval}: {e}")
        return None

# --- Последняя цена ---
def fetch_last_price(ticker):
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}.json"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        payload = r.json()
        securities = payload.get("securities", {})
        cols = securities.get("columns", [])
        rows = securities.get("data", [])
        if not rows or not cols:
            return None
        if "LAST" in cols:
            idx = cols.index("LAST")
            last_price = rows[0][idx]
            if last_price is not None:
                return float(last_price)
    except Exception as e:
        print(f"[ISS] error fetching last price for {ticker}: {e}")
    return None

# --- Расчёт RSI14 ---
def compute_rsi(prices, period=RSI_PERIOD):
    if len(prices) < period + 1:
        return None
    s = pd.Series(prices, dtype="float64")
    delta = s.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)

# --- Построение строки RSI для одного инструмента ---
def build_rsi_row_for_instrument(ticker):
    out = {}
    
    for tf_name, interval in [("5m", "1"), ("1h", "60")]:
        days = LOOKBACK_DAYS[tf_name]
        df = fetch_moex_candles(ticker, interval, days)
        if df is None or df.empty:
            out[tf_name] = {"RSI": "-", "time": "-"}
            continue
        close_col = next((c for c in df.columns if c.lower() == "close"), None)
        begin_col = next((c for c in df.columns if c.lower() == "begin"), None)
        if close_col is None:
            out[tf_name] = {"RSI": "-", "time": "-"}
            continue
        
        # Берём последние RSI_PERIOD свечей
        closes = list(df[close_col].astype(float).values[-RSI_PERIOD:])
        
        # Для часового TF добавляем текущую цену
        if tf_name == "1h":
            last_price = fetch_last_price(ticker)
            if last_price is not None:
                closes.append(last_price)
        
        rsi_val = compute_rsi(closes)
        
        # Время последней свечи
        last_time_str = "-"
        if begin_col:
            try:
                last_ts = pd.to_datetime(df[begin_col].iloc[-1])
                if last_ts.tzinfo is None:
                    last_ts += timedelta(hours=3)
                else:
                    last_ts = last_ts.tz_convert(timezone(timedelta(hours=3)))
                last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                last_time_str = str(df[begin_col].iloc[-1])
        
        out[tf_name] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}
    
    return out

# --- Фоновый поток для кэша ---
def refresh_cache():
    global RSI_CACHE
    while True:
        new_cache = {}
        for name, ticker in INSTRUMENTS.items():
            try:
                new_cache[name] = build_rsi_row_for_instrument(ticker)
            except Exception as e:
                print(f"[ERROR] {name} ({ticker}): {e}")
                new_cache[name] = {"5m": {"RSI": "-", "time": "-"}, "1h": {"RSI": "-", "time": "-"}}
        with CACHE_LOCK:
            RSI_CACHE = new_cache
        time.sleep(60)

# --- Flask API ---
@app.route("/api/rsi")
def api_rsi():
    with CACHE_LOCK:
        return jsonify(RSI_CACHE)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    threading.Thread(target=refresh_cache, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
