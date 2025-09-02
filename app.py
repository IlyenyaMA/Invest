from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__, static_folder="static")
CACHE = {}

# Тикеры MOEX для примера
INSTRUMENTS = {
    "Сбербанк": "SBER",
    "Газпром": "GAZP",
    "Лукойл": "LKOH",
    "Яндекс": "YNDX",
}

TIMEFRAMES = {
    "5m": 5,
    "1h": 60,
}

LOOKBACK_DAYS = {
    "5m": 3,
    "1h": 60,
}

# ===== Расчёт RSI =====
def compute_rsi(prices: pd.Series, period: int = 14) -> float:
    delta = prices.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(span=period, adjust=False).mean()
    roll_down = down.ewm(span=period, adjust=False).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)

# ===== Получение свечей с MOEX =====
def fetch_moex_candles(ticker: str, interval_minutes: int, days: int):
    now = datetime.utcnow()
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
    params = {"from": start, "till": end, "interval": interval_minutes}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        payload = r.json()
        data = payload.get("candles", {})
        cols = data.get("columns", [])
        rows = data.get("data", [])
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=cols)
        if 'CLOSE' not in df.columns or 'BEGIN' not in df.columns:
            return None
        df['CLOSE'] = pd.to_numeric(df['CLOSE'], errors='coerce')
        df['BEGIN'] = pd.to_datetime(df['BEGIN'])
        df = df.dropna(subset=['CLOSE', 'BEGIN'])
        return df
    except Exception as e:
        print(f"[MOEX] Ошибка для {ticker}: {e}")
        return None

# ===== Строим строку RSI для инструмента =====
def build_rsi_row(ticker: str):
    out = {}
    for tf_name, interval in TIMEFRAMES.items():
        days = LOOKBACK_DAYS[tf_name]
        df = fetch_moex_candles(ticker, interval, days)
        if df is None or df.empty or len(df) < 15:
            out[tf_name] = {"RSI": "-", "time": "-"}
            continue
        closes = df['CLOSE']
        rsi_val = compute_rsi(closes)
        last_time = (df['BEGIN'].iloc[-1] + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        out[tf_name] = {"RSI": rsi_val, "time": last_time}
        time.sleep(0.02)  # чтобы не перегружать MOEX
    return out

# ===== Фоновый поток обновления =====
def refresh_cache():
    global CACHE
    while True:
        results = {}
        for name, ticker in INSTRUMENTS.items():
            results[name] = build_rsi_row(ticker)
        CACHE = results
        print(f"🔄 Cache updated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        time.sleep(60)

# ===== Flask маршруты =====
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/rsi")
def api_rsi():
    return jsonify(CACHE)

if __name__ == "__main__":
    t = threading.Thread(target=refresh_cache, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000)
