from flask import Flask, jsonify
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta, timezone
import pandas as pd

TOKEN = "ТВОЙ_ТОКЕН"

INSTRUMENTS = {
    "GAZP": "BBG004730N88",
    "SBER": "BBG004730RP0",
    "LKOH": "BBG004731032",
}

TIMEFRAMES = {
    "5m": CandleInterval.CANDLE_INTERVAL_5_MIN,
    "1h": CandleInterval.CANDLE_INTERVAL_HOUR,
}

def get_days_for_interval(tf_name):
    if tf_name == "5m":
        return 7
    elif tf_name == "1h":
        return 10
    return 30

def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down
    return 100 - (100 / (1 + rs))

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
        print(f"Не удалось получить last_price для {figi}: {e}")

    rsi_val = round(rsi(pd.Series(closes)).iloc[-1], 2)

    last_time = candles[-1].time.astimezone(
        timezone(timedelta(hours=3))
    ).strftime("%Y-%m-%d %H:%M:%S")

    return rsi_val, last_time


app = Flask(__name__)

@app.route("/data")
def get_data():
    results = {}
    with Client(TOKEN) as client:
        for name, figi in INSTRUMENTS.items():
            results[name] = {}
            for tf_name, interval in TIMEFRAMES.items():
                val, last_time = get_rsi(client, figi, tf_name, interval)
                if val is not None:
                    results[name][tf_name] = {
                        "rsi": val,
                        "time": last_time
                    }
                else:
                    results[name][tf_name] = {
                        "rsi": "-",
                        "time": "-"
                    }
    return jsonify(results)

if __name__ == "__main__":
    app.run(debug=True)
