from flask import Flask, jsonify, send_from_directory
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta, timezone
import pandas as pd

app = Flask(__name__, static_folder="static")

TOKEN = "твой токен"

INSTRUMENTS = {
    "Озон фарма": "TCS00A109B25",
    "Башнефть": "BBG004S68758"
    # добавь остальные инструменты
}

TIMEFRAMES = {
    "5m": CandleInterval.CANDLE_INTERVAL_5_MIN,
    "1h": CandleInterval.CANDLE_INTERVAL_HOUR
}

def compute_rsi(prices, period=14):
    df = pd.DataFrame(prices, columns=["close"])
    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2) if not rsi.empty else None

def fetch_rsi():
    results = {}
    with Client(TOKEN) as client:
        for name, figi in INSTRUMENTS.items():
            results[name] = {}
            for tf_name, interval in TIMEFRAMES.items():
                try:
                    now = datetime.now(timezone.utc)
                    start = now - timedelta(days=30)
                    candles = client.market_data.get_candles(
                        figi=figi,
                        from_=start,
                        to=now,
                        interval=interval
                    ).candles
                    if not candles:
                        results[name][tf_name] = {"RSI": "-", "time": "-"}
                        continue

                    closes = [c.close.units + c.close.nano/1e9 for c in candles]
                    rsi_val = compute_rsi(closes)
                    last_time = candles[-1].time.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
                    results[name][tf_name] = {"RSI": rsi_val, "time": last_time}
                except:
                    results[name][tf_name] = {"RSI": "-", "time": "-"}
    return results

@app.route("/api/rsi")
def api_rsi():
    return jsonify(fetch_rsi())

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
