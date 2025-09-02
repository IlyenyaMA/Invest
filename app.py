from flask import Flask, jsonify, send_from_directory
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta, timezone
import pandas as pd

TOKEN = "t.a_yTo2QKdKX0FFwrNTmkvlKAfBml74hg7SVdW-GbyAVhY5znKubj2meA61ufoYGu_awUxQvozh07QHBrY3OgZA"

# FIGI инструментов
INSTRUMENTS = {
    "GAZP": "BBG004730RP0",
    "SBER": "BBG004730N88",
    "LKOH": "BBG004731032"
}

TIMEFRAMES = {
    "5m": CandleInterval.CANDLE_INTERVAL_5_MIN,
    "1h": CandleInterval.CANDLE_INTERVAL_HOUR,
    "1d": CandleInterval.CANDLE_INTERVAL_DAY
}

def get_days_for_interval(tf_name):
    if tf_name == "5m":
        return 7
    elif tf_name == "1h":
        return 10
    elif tf_name == "1d":
        return 365
    return 30

def rsi(closes, period=14):
    series = pd.Series(closes)
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi

def get_rsi(client, figi, tf_name, interval):
    days = get_days_for_interval(tf_name)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    candles = client.market_data.get_candles(
        figi=figi,
        from_=start,
        to=now,
        interval=interval
    ).candles

    if not candles or len(candles) < 15:
        return None

    closes = [c.close.units + c.close.nano / 1e9 for c in candles]

    # заменяем последний close на актуальную цену
    last_price_resp = client.market_data.get_last_prices(figi=[figi])
    if last_price_resp.last_prices:
        current_price = (
            last_price_resp.last_prices[0].price.units
            + last_price_resp.last_prices[0].price.nano / 1e9
        )
        closes[-1] = current_price

    rsi_series = rsi(closes, 14)
    return round(rsi_series.iloc[-1], 2)

# Flask
app = Flask(__name__, static_folder="static")

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/data")
def data():
    results = {}
    with Client(TOKEN) as client:
        for name, figi in INSTRUMENTS.items():
            results[name] = {}
            for tf_name, interval in TIMEFRAMES.items():
                val = get_rsi(client, figi, tf_name, interval)
                results[name][tf_name] = val if val is not None else "-"
    return jsonify(results)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
