from flask import Flask, jsonify, send_from_directory
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta, timezone
import pandas as pd
import os

# index.html лежит в ./static
app = Flask(__name__, static_folder="static")

# Безопаснее брать токен из переменной окружения
TOKEN = os.getenv("TINKOFF_TOKEN", "ВСТАВЬ_ТОКЕН_ДЛЯ_ЛОКАЛЬНОГО_ТЕСТА")

# ВСТАВЬ сюда твой большой словарь INSTRUMENTS БЕЗ ИЗМЕНЕНИЙ
# Он может содержать и BBG... (FIGI), и TCS... (instrument_uid)
INSTRUMENTS = {
    "Башнефть": "BBG004S68758",
    "Озон фарма": "TCS00A109B25",
    # ... остальной твой список
}

TIMEFRAMES = {
    "5m": CandleInterval.CANDLE_INTERVAL_5_MIN,
    "1h": CandleInterval.CANDLE_INTERVAL_HOUR,
}

# Сколько дней истории запрашивать (коротко для 5м, длиннее для 1ч)
LOOKBACK_DAYS = {
    "5m": 3,     # 3 дня достаточно для RSI и не бьёт лимиты
    "1h": 60,    # 60 дней для часа
}

def compute_rsi(prices, period: int = 14):
    """RSI по закрытиям. Возвращает float или None, если данных мало."""
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

def get_candles(client: Client, instrument_id: str, tf_name: str):
    """
    Универсальный запрос свечей через instrument_id (подходит и для BBG..., и для TCS...).
    Возвращает список свечей или пустой список.
    """
    interval = TIMEFRAMES[tf_name]
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=LOOKBACK_DAYS[tf_name])
    try:
        resp = client.market_data.get_candles(
            instrument_id=instrument_id,   # ВАЖНО: не figi=..., а instrument_id=...
            from_=start,
            to=now,
            interval=interval,
        )
        return resp.candles or []
    except Exception as e:
        # Можно посмотреть ошибку в логах
        print(f"{instrument_id} {tf_name} get_candles error: {e}")
        return []

def build_row(client: Client, instrument_id: str):
    """Собираем RSI и время для 5m и 1h по одному инструменту."""
    out = {}
    for tf_name in TIMEFRAMES.keys():
        candles = get_candles(client, instrument_id, tf_name)
        if not candles:
            out[tf_name] = {"RSI": "-", "time": "-"}
            continue

        closes = [c.close.units + c.close.nano / 1e9 for c in candles]
        rsi_val = compute_rsi(closes)
        # время последней свечи в МСК
        last_ts = candles[-1].time.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")

        out[tf_name] = {
            "RSI": rsi_val if rsi_val is not None else "-",
            "time": last_ts,
        }
    return out

@app.route("/api/rsi")
def api_rsi():
    results = {}
    # Один клиент на все запросы
    with Client(TOKEN) as client:
        for name, instrument_id in INSTRUMENTS.items():
            results[name] = build_row(client, instrument_id)
    return jsonify(results)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    # Локально: python app.py
    app.run(host="0.0.0.0", port=5000)
