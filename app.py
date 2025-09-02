# app.py — Flask backend (MOEX ISS, RSI по 5m и 1h)
from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

app = Flask(__name__, static_folder="static")

# ✅ Используем чистые MOEX тикеры (работают гарантированно)
INSTRUMENTS = {
    "Сбербанк": "SBER",
    "Газпром": "GAZP",
    "Лукойл": "LKOH",
    "Яндекс": "YNDX",
}

# Периоды загрузки
LOOKBACK_DAYS = {
    "5m": 1,    # для минуток достаточно 1 дня
    "1h": 30,   # для часов — месяц
}

def fetch_moex_candles(ticker: str, interval: str, days: int):
    """Запрашивает свечи у MOEX ISS"""
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

def compute_rsi_from_list(prices, period=14):
    """Вычисляет RSI"""
    if len(prices) < period + 1:
        return None
    s = pd.Series(prices, dtype="float64")
    delta = s.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)

def build_rsi_row_for_instrument(ticker):
    """Возвращает RSI по 5м и 1ч"""
    out = {}

    # --- 5m (агрегация из 1m)
    df_1m = fetch_moex_candles(ticker, "1", LOOKBACK_DAYS["5m"])
    if df_1m is not None and not df_1m.empty:
        close_col = next((c for c in df_1m.columns if c.lower() == "close"), None)
        begin_col = next((c for c in df_1m.columns if c.lower() == "begin"), None)
        if close_col:
            df_5m = df_1m.iloc[::5, :].reset_index(drop=True)
            closes = list(df_5m[close_col].astype(float).values)
            rsi_val = compute_rsi_from_list(closes)
            last_time_str = "-"
            if begin_col:
                try:
                    last_ts = pd.to_datetime(df_5m[begin_col].iloc[-1])
                    if last_ts.tzinfo is None:
                        last_ts = last_ts + timedelta(hours=3)
                    else:
                        last_ts = last_ts.tz_convert(timezone(timedelta(hours=3)))
                    last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    last_time_str = str(df_5m[begin_col].iloc[-1])
            out["5m"] = {"RSI": rsi_val if rsi_val else "-", "time": last_time_str}
        else:
            out["5m"] = {"RSI": "-", "time": "-"}
    else:
        out["5m"] = {"RSI": "-", "time": "-"}

    # --- 1h
    df_1h = fetch_moex_candles(ticker, "60", LOOKBACK_DAYS["1h"])
    if df_1h is not None and not df_1h.empty:
        close_col = next((c for c in df_1h.columns if c.lower() == "close"), None)
        begin_col = next((c for c in df_1h.columns if c.lower() == "begin"), None)
        if close_col:
            closes = list(df_1h[close_col].astype(float).values)
            rsi_val = compute_rsi_from_list(closes)
            last_time_str = "-"
            if begin_col:
                try:
                    last_ts = pd.to_datetime(df_1h[begin_col].iloc[-1])
                    if last_ts.tzinfo is None:
                        last_ts = last_ts + timedelta(hours=3)
                    else:
                        last_ts = last_ts.tz_convert(timezone(timedelta(hours=3)))
                    last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    last_time_str = str(df_1h[begin_col].iloc[-1])
            out["1h"] = {"RSI": rsi_val if rsi_val else "-", "time": last_time_str}
        else:
            out["1h"] = {"RSI": "-", "time": "-"}
    else:
        out["1h"] = {"RSI": "-", "time": "-"}

    return out

@app.route("/api/rsi")
def api_rsi():
    results = {}
    for name, ticker in INSTRUMENTS.items():
        try:
            results[name] = build_rsi_row_for_instrument(ticker)
        except Exception as e:
            print(f"[ERROR] {name} ({ticker}): {e}")
            results[name] = {"5m": {"RSI": "-", "time": "-"}, "1h": {"RSI": "-", "time": "-"}}
    return jsonify(results)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
