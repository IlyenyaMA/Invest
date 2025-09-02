# app.py
from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

app = Flask(__name__, static_folder="static")

# --- Здесь укажи свои инструменты в формате name -> MOEX_TICKER (пример ниже) ---
# ВАЖНО: это MOEX-тикеры (SBER, GAZP, LKOH ...), а не FIGI.
INSTRUMENTS = {
    "Сбербанк": "SBER",
    "Газпром": "GAZP",
    "Лукойл": "LKOH",
    "Яндекс": "YNDX",
    "ВТБ": "VTBR",
}

# ТФ: значение interval для MOEX ISS API (минуты или 'week')
TIMEFRAMES = {
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1d": "24",
    "1w": "week",
}

# Сколько дней запрашивать для каждого ТФ (чтобы не получить INVALID_ARGUMENT)
LOOKBACK_DAYS = {
    "5m": 3,
    "15m": 7,
    "1h": 60,
    "4h": 120,
    "1d": 365,
    "1w": 5 * 365,
}

def compute_rsi_from_list(prices, period=14):
    """Простая реализация RSI через pandas ewm."""
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
    try:
        return round(float(rsi.iloc[-1]), 2)
    except Exception:
        return None

def fetch_moex_candles(ticker: str, interval: str, days: int):
    """Запрашиваем свечи с MOEX ISS. Возвращаем DataFrame или None."""
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
    now = datetime.utcnow()
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    params = {"from": start, "till": end, "interval": interval}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        payload = r.json()
        candles = payload.get("candles", {})
        cols = candles.get("columns", [])
        rows = candles.get("data", [])
        if not rows or not cols:
            return None
        df = pd.DataFrame(rows, columns=cols)
        # CLOSE column может быть строкой — принудительно в float
        if "CLOSE" not in df.columns:
            return None
        df["CLOSE"] = df["CLOSE"].astype(float)
        return df
    except Exception as e:
        # не прерываем работу — вернём None и обработаем на стороне вызова
        print(f"[MOEX] error fetching {ticker} interval={interval}: {e}")
        return None

def build_rsi_row(ticker):
    """Возвращает dict с RSI и временем для всех TF для данного тикера."""
    out = {}
    for tf_name, interval in TIMEFRAMES.items():
        days = LOOKBACK_DAYS.get(tf_name, 30)
        df = fetch_moex_candles(ticker, interval, days)
        if df is None or df.empty:
            out[tf_name] = {"RSI": "-", "time": "-"}
            continue
        closes = list(df["CLOSE"].values)
        rsi_val = compute_rsi_from_list(closes)
        # пробуем взять столбец с временем: "BEGIN" или "begin"
        time_col = None
        for c in df.columns:
            if c.lower() == "begin":
                time_col = c
                break
        last_time_str = "-"
        if time_col:
            try:
                last_ts = pd.to_datetime(df[time_col].iloc[-1])
                # если без tz — считаем как UTC и добавляем +3 часа для МСК
                if last_ts.tzinfo is None:
                    last_ts = last_ts + timedelta(hours=3)
                else:
                    last_ts = last_ts.tz_convert(timezone(timedelta(hours=3)))
                last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                last_time_str = str(df[time_col].iloc[-1])
        out[tf_name] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}
        # небольшая пауза, чтобы не нагружать ISS при огромном списке
        time.sleep(0.05)
    return out

@app.route("/api/rsi")
def api_rsi():
    results = {}
    for name, ticker in INSTRUMENTS.items():
        try:
            results[name] = build_rsi_row(ticker)
        except Exception as e:
            print(f"Ошибка для {name}/{ticker}: {e}")
            results[name] = {tf: {"RSI": "-", "time": "-"} for tf in TIMEFRAMES.keys()}
    return jsonify(results)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    # Запуск: python app.py
    app.run(host="0.0.0.0", port=5000)
