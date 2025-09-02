from flask import Flask, jsonify, send_from_directory
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta, timezone
import pandas as pd

app = Flask(__name__, static_folder="static")

# Токен для Tinkoff API
TOKEN = "t.a_yTo2QKdKX0FFwrNTmkvlKAfBml74hg7SVdW-GbyAVhY5znKubj2meA61ufoYGu_awUxQvozh07QHBrY3OgZA"

# Словарь инструментов: название → FIGI или instrument_uid
INSTRUMENTS = {
    "Башнефть": "BBG004S68758",
    "Трубная Металлургическая Компания": "BBG004TC84Z8",
    "Московская Биржа": "BBG004730JJ5",
    "Башнефть — привилегированные акции": "BBG004S686N0",
    "РУСАЛ": "BBG008F2T3T2",
    "Таттелеком": "BBG000RJL816",
    "МРСК Урала": "BBG000VKG4R5",
    "Норильский никель": "BBG004731489",
    "МРСК Северо-Запада": "BBG000TJ6F42",
    "ТГК-2": "BBG000Q7GG57",
    "ПАО «КАЗАНЬОРГСИНТЕЗ»": "BBG0029SFXB3",
    "МОЭСК": "BBG004S687G6",
    "QIWI": "BBG005D1WCQ1",
    "Корпорация ИРКУТ": "BBG000FWGSZ5",
    "Юнипро": "BBG004S686W0",
    "Мечел — привилегированные акции": "BBG004S68FR6",
    "Ленэнерго": "BBG000NLC9Z6",
    "РусГидро": "BBG00475K2X9",
    "Ростелеком — привилегированные акции": "BBG004S685M3",
    "Yandex": "TCS00A107T19",
    "АФК Система": "BBG004S68614",
    "Банк ВТБ": "BBG004730ZJ9",
    "Роснефть": "BBG004731354",
    "Сбербанк России": "BBG004730N88",
    # … продолжение словаря …
}

# Таймфреймы для RSI
TIMEFRAMES = {
    "5m": CandleInterval.CANDLE_INTERVAL_5_MIN,
    "1h": CandleInterval.CANDLE_INTERVAL_HOUR
}

def compute_rsi(prices, period=14):
    """
    Вычисляет RSI по списку цен закрытия.
    Возвращает float или None, если данных недостаточно.
    """
    if len(prices) < period + 1:
        return None

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
    """
    Собирает RSI для всех инструментов и таймфреймов.
    Возвращает словарь: {название_инструмента: {tf: {"RSI": ..., "time": ...}}}
    """
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

                    closes = [c.close.units + c.close.nano / 1e9 for c in candles]
                    rsi_val = compute_rsi(closes)
                    last_time = candles[-1].time.astimezone(
                        timezone(timedelta(hours=3))
                    ).strftime("%Y-%m-%d %H:%M:%S")

                    results[name][tf_name] = {"RSI": rsi_val, "time": last_time}

                except Exception:
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
