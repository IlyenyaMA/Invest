# app.py — RSI14: ровно 14 предыдущих свечей + актуальная цена (MOEX ISS)
from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import threading
import time

app = Flask(__name__, static_folder="static")

# ---------------- Конфигурация ----------------
INSTRUMENTS = {
    "Сбербанк": "SBER",
    "Газпром": "GAZP",
    "Лукойл": "LKOH",
    "Яндекс": "YNDX",
}

LOOKBACK_DAYS = {
    "5m": 7,    # загружаем 1m за 7 дней и агрегируем в 5m
    "1h": 10,   # загружаем 60m за 10 дней
}

RSI_PERIOD = 14
REFRESH_SECONDS = 60

RSI_CACHE = {}
CACHE_LOCK = threading.Lock()

# ---------------- Вспомогательные функции ----------------

def fetch_moex_candles(ticker: str, interval: str, days: int):
    """
    Возвращает DataFrame с колонками, как отдает MOEX ISS, либо None.
    interval: строка "1" или "60" и т.д.
    """
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
    """
    Получаем актуальную цену (LAST) через securities endpoint.
    Ищем колонку, содержащую 'last' (без учёта регистра).
    Возвращаем float или None.
    """
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
            if "last" in str(c).lower():
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

def compute_rsi_wilder_window(prices, period=RSI_PERIOD):
    """
    Рассчитывает RSI14 по методу Wilder, инициализация внутри окна.
    prices: list/np.array/pd.Series чисел (ordered asc by time).
    Требование: len(prices) >= period + 1 (т.е. 15 элементов для RSI14).
    Возвращает float округл.2 или None.
    """
    arr = np.asarray(prices, dtype="float64")
    if arr.size < period + 1:
        return None

    deltas = np.diff(arr)  # length n-1 (для 15 цен — 14 дельт)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # инициализация по первым `period` дельтам (gains[0:period])
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()

    # если есть дополнительные дельты (больше period), применяем рекурсивно
    for i in range(period, gains.size):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        if avg_gain == 0.0:
            return 50.0
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(float(rsi), 2)

# ---------------- Подготовка последовательности: ровно 14 пред. свечей + актуальная цена ----------------

def build_series_last14_plus_price(closes_series, last_price):
    """
    closes_series: pd.Series или list из закрытий (ordered asc).
    last_price: float or None.
    Возвращает tuple (sequence_list, used_last_price_flag) либо (None, False), если невозможно собрать окно.
    Мы строго берём **последние 14 закрытий** и добавляем last_price в конец.
    Требование: len(closes_series) >= 14 and last_price is not None -> вернётся 15 элементов.
    """
    vals = list(pd.to_numeric(pd.Series(closes_series), errors="coerce").dropna().values)
    if len(vals) < RSI_PERIOD:
        return None, False
    base = vals[-RSI_PERIOD:]  # ровно 14 предыдущих закрытий
    if last_price is None:
        return None, False
    seq = base + [float(last_price)]
    return seq, True

# ---------------- Основная: построение строки RSI для инструмента ----------------

def build_rsi_row_for_instrument(ticker: str):
    out = {}

    # ---- 5m: загружаем 1m и агрегируем в 5m корректно через resample ----
    df1m = fetch_moex_candles(ticker, "1", LOOKBACK_DAYS["5m"])
    if df1m is None or df1m.empty:
        out["5m"] = {"RSI": "-", "time": "-"}
    else:
        # найти названия колонок case-insensitive
        colmap = {c.lower(): c for c in df1m.columns}
        if "close" not in colmap or "begin" not in colmap:
            out["5m"] = {"RSI": "-", "time": "-"}
        else:
            close_col = colmap["close"]
            begin_col = colmap["begin"]
            # parse begin -> tz-aware UTC
            df1m["dt"] = pd.to_datetime(df1m[begin_col], utc=True, errors="coerce")
            df1m = df1m.dropna(subset=["dt"])
            if df1m.empty:
                out["5m"] = {"RSI": "-", "time": "-"}
            else:
                df1m = df1m.set_index("dt").sort_index()
                # агрегируем в 5 минут: last close в окне
                # label='right', closed='right' — чтобы бар 10:00 покрывал 09:55-10:00
                r5 = df1m.resample("5T", label="right", closed="right").agg({close_col: "last"})
                r5 = r5.dropna(subset=[close_col])
                if r5.empty or len(r5) < RSI_PERIOD:
                    out["5m"] = {"RSI": "-", "time": "-"}
                else:
                    closes_5m = r5[close_col].astype(float)
                    last_price = fetch_last_price(ticker)
                    seq, used_now = build_series_last14_plus_price(closes_5m, last_price)
                    if seq is None:
                        out["5m"] = {"RSI": "-", "time": "-"}
                    else:
                        rsi_val = compute_rsi_wilder_window(seq, period=RSI_PERIOD)
                        if used_now:
                            last_time_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            # отображаем время последней закрытой 5m свечи (MSK)
                            last_idx = r5.index[-1]
                            last_time_str = (last_idx + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
                        out["5m"] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}

    # ---- 1h: берём 60m напрямую ----
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
            if df1h.empty or len(df1h) < RSI_PERIOD:
                out["1h"] = {"RSI": "-", "time": "-"}
            else:
                closes_h = df1h[close_col_h].astype(float)
                last_price_h = fetch_last_price(ticker)
                seq_h, used_now_h = build_series_last14_plus_price(closes_h, last_price_h)
                if seq_h is None:
                    out["1h"] = {"RSI": "-", "time": "-"}
                else:
                    rsi_h = compute_rsi_wilder_window(seq_h, period=RSI_PERIOD)
                    if used_now_h:
                        last_time_str_h = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        try:
                            last_ts = pd.to_datetime(df1h[begin_col_h].iloc[-1], utc=True)
                            last_time_str_h = (last_ts + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            last_time_str_h = "-"
                    out["1h"] = {"RSI": rsi_h if rsi_h is not None else "-", "time": last_time_str_h}

    return out

# ---------------- Фоновое обновление кэша ----------------

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

# ---------------- HTTP ----------------

@app.route("/api/rsi")
def api_rsi():
    with CACHE_LOCK:
        return jsonify(RSI_CACHE)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

# ---------------- MAIN ----------------
if __name__ == "__main__":
    threading.Thread(target=refresh_cache, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
