# app.py — корректный RSI14 (EWMA) с актуальной ценой, MOEX ISS
from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import threading
import time

app = Flask(__name__, static_folder="static")

# --- Настройки: тикеры MOEX (можешь поменять на свои) ---
INSTRUMENTS = {
    "Сбербанк": "SBER",
    "Газпром": "GAZP",
    "Лукойл": "LKOH",
    "Яндекс": "YNDX",
}

# сколько дней брать для исходных свечей
LOOKBACK_DAYS = {
    "5m": 7,   # загрузим 1m за 7 дней и агрегируем в 5m
    "1h": 10,  # загрузим 60m за 10 дней
}

RSI_PERIOD = 14            # RSI14
REFRESH_SECONDS = 60       # обновление кэша
RSI_CACHE = {}
CACHE_LOCK = threading.Lock()

# --------------------- HELPERS ---------------------

def fetch_moex_candles(ticker: str, interval: str, days: int):
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
    now_utc = datetime.utcnow()
    start = (now_utc - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"from": start, "till": now_utc.strftime("%Y-%m-%d"), "interval": interval}
    try:
        r = requests.get(url, params=params, timeout=12)
        r.raise_for_status()
        payload = r.json()
        candles = payload.get("candles", {})
        cols = candles.get("columns", [])
        rows = candles.get("data", [])
        if not rows or not cols:
            return None
        df = pd.DataFrame(rows, columns=cols)
        return df
    except Exception as e:
        print(f"[MOEX] error fetching candles for {ticker} interval={interval}: {e}")
        return None

def fetch_last_price(ticker: str):
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}.json"
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        payload = r.json()
        sec = payload.get("securities", {})
        cols = sec.get("columns", [])
        rows = sec.get("data", [])
        if not cols or not rows:
            return None
        for i, c in enumerate(cols):
            if str(c).lower() == "last":
                val = rows[0][i]
                if val is None:
                    return None
                try:
                    return float(val)
                except:
                    return None
        return None
    except Exception as e:
        print(f"[MOEX] error fetching last price for {ticker}: {e}")
        return None

# --------------------- RSI через EWM ---------------------

def compute_rsi_ewm(prices, period=RSI_PERIOD):
    series = pd.Series(prices)
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2) if not rsi.empty else None

def prepare_rsi_sequence(closes_series, last_price, period=RSI_PERIOD):
    vals = list(pd.to_numeric(pd.Series(closes_series), errors='coerce').dropna().values)
    if len(vals) < period:
        return None
    # заменяем последнюю цену на актуальную
    if last_price is not None:
        vals[-1] = last_price
    return vals

# --------------------- Ядро ---------------------

def build_rsi_row_for_instrument(ticker: str):
    out = {}

    # ---------- 5m: агрегация 1m -> 5m ----------
    df1m = fetch_moex_candles(ticker, "1", LOOKBACK_DAYS["5m"])
    if df1m is None or df1m.empty:
        out["5m"] = {"RSI": "-", "time": "-"}
    else:
        colmap = {c.lower(): c for c in df1m.columns}
        if "close" not in colmap or "begin" not in colmap:
            out["5m"] = {"RSI": "-", "time": "-"}
        else:
            close_col = colmap["close"]
            begin_col = colmap["begin"]
            df1m["dt"] = pd.to_datetime(df1m[begin_col], utc=True, errors="coerce")
            df1m = df1m.dropna(subset=["dt"]).set_index("dt").sort_index()
            r5 = df1m.resample("5T", label="right", closed="right").agg({close_col: "last"})
            r5 = r5.dropna(subset=[close_col])
            if r5.empty:
                out["5m"] = {"RSI": "-", "time": "-"}
            else:
                closes_5m = r5[close_col].astype(float)
                last_price = fetch_last_price(ticker)
                seq = prepare_rsi_sequence(closes_5m, last_price, period=RSI_PERIOD)
                if seq is None:
                    out["5m"] = {"RSI": "-", "time": "-"}
                else:
                    rsi_val = compute_rsi_ewm(seq, period=RSI_PERIOD)
                    last_time_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
                    out["5m"] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}

    # ---------- 1h ----------
    df1h = fetch_moex_candles(ticker, "60", LOOKBACK_DAYS["1h"])
    if df1h is None or df1h.empty:
        out["1h"] = {"RSI": "-", "time": "-"}
    else:
        colmap_h = {c.lower(): c for c in df1h.columns}
        if "close" not in colmap_h or "begin" not in colmap_h:
            out["1h"] = {"RSI": "-", "time": "-"}
        else:
            close_col_h = colmap_h["close"]
            begin_col_h = colmap_h["begin"]
            df1h[begin_col_h] = pd.to_datetime(df1h[begin_col_h], utc=True, errors="coerce")
            df1h = df1h.dropna(subset=[close_col_h])
            if df1h.empty:
                out["1h"] = {"RSI": "-", "time": "-"}
            else:
                closes_h = df1h[close_col_h].astype(float)
                last_price_h = fetch_last_price(ticker)
                seq_h = prepare_rsi_sequence(closes_h, last_price_h, period=RSI_PERIOD)
                if seq_h is None:
                    out["1h"] = {"RSI": "-", "time": "-"}
                else:
                    rsi_h = compute_rsi_ewm(seq_h, period=RSI_PERIOD)
                    last_time_str_h = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
                    out["1h"] = {"RSI": rsi_h if rsi_h is not None else "-", "time": last_time_str_h}

    return out

# --------------------- Кэш ---------------------
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
            time.sleep(0.05)
        with CACHE_LOCK:
            RSI_CACHE = new_cache
        print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Cache updated")
        time.sleep(REFRESH_SECONDS)

# --------------------- Маршруты ---------------------
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
