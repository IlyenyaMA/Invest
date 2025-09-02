import pandas as pd
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta, timezone
from IPython.display import display

TOKEN = "ТВОЙ_ТОКЕН"

# Акции/фонды (FIGI должны быть корректными!)
INSTRUMENTS = {
    "Сбербанк": "BBG004730N88",
    "Газпром": "BBG004730RP0",
    "Лукойл": "BBG004730ZJ9",
    "Яндекс": "BBG006L8G4H1",  # заменил на корректный FIGI из Тинькофф
    "Фонд крупнейшие компании РФ": "TCS00A102F40",  # реальный FIGI фонда
    "Фонд золото": "TCS00A100FQ8"  # реальный FIGI фонда золота
}

# Таймфреймы
TIMEFRAMES = {
    "5m": CandleInterval.CANDLE_INTERVAL_5_MIN,
    "15m": CandleInterval.CANDLE_INTERVAL_15_MIN,
    "1h": CandleInterval.CANDLE_INTERVAL_HOUR,
    "4h": CandleInterval.CANDLE_INTERVAL_4_HOUR,
    "1d": CandleInterval.CANDLE_INTERVAL_DAY,
    "1w": CandleInterval.CANDLE_INTERVAL_WEEK
}

# Периоды подкачки истории
def get_days_for_interval(tf_name):
    if tf_name in ["5m", "15m"]:
        return 7
    elif tf_name in ["1h", "4h"]:
        return 60
    elif tf_name == "1d":
        return 365
    elif tf_name == "1w":
        return 5*365
    return 30

# Перевод Quotation → float
def quotation_to_float(q):
    return q.units + q.nano / 1e9

# RSI
def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down
    return 100 - (100 / (1 + rs))

# Получение RSI
def get_rsi(client, figi, tf_name, interval):
    days = get_days_for_interval(tf_name)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    try:
        candles = client.market_data.get_candles(
            figi=figi,
            from_=start,
            to=now,
            interval=interval
        ).candles
    except Exception as e:
        print(f"Ошибка для FIGI {figi} ({tf_name}): {e}")
        return None, None

    if not candles or len(candles) < 15:
        return None, None

    closes = [quotation_to_float(c.close) for c in candles]
    rsi_val = round(rsi(pd.Series(closes)).iloc[-1], 2)
    last_time = candles[-1].time.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
    return rsi_val, last_time

# Подсветка RSI
def highlight_rsi(val):
    try:
        rsi_val = float(val.split(" ")[0])
        if rsi_val < 30 or rsi_val > 70:
            return "background-color: lightgreen"
    except:
        pass
    return ""

# Сбор данных
results = {}

with Client(TOKEN) as client:
    for name in INSTRUMENTS:
        results[name] = {}
    for tf_name, interval in TIMEFRAMES.items():
        for name, figi in INSTRUMENTS.items():
            val, last_time = get_rsi(client, figi, tf_name, interval)
            if val is not None:
                results[name][tf_name] = f"{val} ({last_time})"
            else:
                results[name][tf_name] = "-"

# Таблица
df = pd.DataFrame(results).T

# Сортировка по RSI (по столбцу)
def sort_by_tf(tf_name):
    if tf_name not in df.columns:
        print(f"Нет такого ТФ: {tf_name}")
        return df
    sorted_df = df.copy()
    sorted_df["_sort"] = sorted_df[tf_name].apply(
        lambda x: float(x.split()[0]) if x != "-" else float("inf")
    )
    sorted_df = sorted_df.sort_values("_sort").drop(columns="_sort")
    return sorted_df

print("RSI14 таблица (RSI14 + время последней свечи, МСК):")
display(df.style.applymap(highlight_rsi))

print("\nСортировка по 1h:")
display(sort_by_tf("1h").style.applymap(highlight_rsi))
