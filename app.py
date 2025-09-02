# app.py — корректный RSI14 (Wilder) с актуальной ценой, MOEX ISS
from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import threading
import time

app = Flask(__name__, static_folder="static")

# --- Настройки: тикеры MOEX (можешь поменять на свои) ---
INSTRUMENTS = {
    "Сбербанк": "SBER",
    "Газпром": "GAZP",
    "Лукойл": "LKOH",
    "Яндекс": "YNDX",
}

# сколько дней брать для исходных свечей
LOOKBACK_DAYS = {
    "5m": 7,   # загрузим 1m за 7 дней и агрегируем в 5m
    "1h": 10,  # загрузим 60m за 10 дней
}

RSI_PERIOD = 14            # RSI14
REFRESH_SECONDS = 60       # обновление кэша
RSI_CACHE = {}
CACHE_LOCK = threading.Lock()

# --------------------- HELPERS ---------------------

def fetch_moex_candles(ticker: str, interval: str, days: int):
    """
    Запрашивает candles.json у MOEX ISS.
    interval: строка с числом, например "1" или "60".
    Возвращает DataFrame (оригинальные имена колонок) или None.
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
    Получаем последнюю (текущую) цену через securities endpoint.
    Возвращает float или None.
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
        # ищем колонку 'LAST' (без учёта регистра)
        for i, c in enumerate(cols):
            if str(c).lower() == "last":
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

# Wilder RSI: корректная инициализация + рекурсивное сглаживание
def compute_rsi_wilder(prices, period=RSI_PERIOD):
    """
    prices: список или np.array или pd.Series чисел (ordered asc by time).
    Возвращает float (округл. 2) или None при недостатке данных.
    Реализация классического Wilder RSI.
    """
    arr = np.asarray(prices, dtype="float64")
    if arr.size < period + 1:
        return None

    deltas = np.diff(arr)  # length = n-1
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # начальные средние по первым `period` дельтам
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()

    # рекурсивно обновляем средние на последующих дельтах
    for i in range(period, gains.size):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    # обработка крайних случаев
    if avg_loss == 0.0:
        if avg_gain == 0.0:
            return 50.0
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(float(rsi), 2)

# Подготовка ряда цен для RSI: строго 14 закрытий + (опционально) last_price
def prepare_rsi_sequence(closes_series, last_price, strict_window=True, period=RSI_PERIOD):
    """
    closes_series: iterable numeric (ascending time).
    last_price: float or None.
    strict_window: если True -> берём последние `period` закрытий и добавляем last_price как +1 (требуется period+1).
                   если False -> используем всю историю (closes_series) и добавляем last_price (при наличии).
    Возвращает (sequence_list, used_last_price_flag) либо (None, False) если недостаточно данных.
    """
    vals = list(pd.to_numeric(pd.Series(closes_series), errors='coerce').dropna().values)
    if strict_window:
        # берем ровно последние period закрытий (если есть) и добавляем last_price
        if len(vals) >= period:
            base = vals[-period:]
        else:
            base = vals[:]  # меньше чем period — попробуем всё, но, возможно, не хватит
        used_last = False
        if last_price is not None:
            cand = base + [last_price]
            if len(cand) >= period + 1:
                return cand, True
            # иначе — попробуем расширить base, если есть дополнительные закрытия
        # fallback: если base недостаточно, но есть достаточно полных закрытий для period+1 — взять их
        if len(vals) >= period + 1:
            return vals[-(period + 1):], False
        return None, False
    else:
        # full history + last_price
        seq = vals[:]
        if last_price is not None:
            seq = seq + [last_price]
        if len(seq) >= period + 1:
            return seq, (last_price is not None)
        return None, False

# --------------------- Ядро: расчёт для одного инструмента ---------------------

def build_rsi_row_for_instrument(ticker: str):
    """
    Возвращает dict {"5m": {"RSI": val_or "-", "time": str}, "1h": {...}}
    """
    out = {}

    # ---------- 5m: агрегация 1m -> 5m ----------
    df1m = fetch_moex_candles(ticker, "1", LOOKBACK_DAYS["5m"])
    if df1m is None or df1m.empty:
        out["5m"] = {"RSI": "-", "time": "-"}
    else:
        # case-insensitive поиск названий колонок
        colmap = {c.lower(): c for c in df1m.columns}
        if "close" not in colmap or "begin" not in colmap:
            out["5m"] = {"RSI": "-", "time": "-"}
        else:
            close_col = colmap["close"]
            begin_col = colmap["begin"]
            # преобразуем время в datetime (UTC) и делаем индекс
            df1m["dt"] = pd.to_datetime(df1m[begin_col], utc=True, errors="coerce")
            df1m = df1m.dropna(subset=["dt"])
            if df1m.empty:
                out["5m"] = {"RSI": "-", "time": "-"}
            else:
                # делаем временной индекс без timezone (на resample это нормально тоже, но проще работать с naive UTC)
                df1m["dt"] = df1m["dt"].dt.tz_convert("UTC").dt.tz_localize(None)
                df1m = df1m.set_index("dt").sort_index()
                # агрегируем в 5 минут (label='right' чтобы последняя тикетная отметка соответствовала правому краю бара)
                r5 = df1m.resample("5T", label="right", closed="right").agg({close_col: "last"})
                r5 = r5.dropna(subset=[close_col])
                if r5.empty:
                    out["5m"] = {"RSI": "-", "time": "-"}
                else:
                    closes_5m = r5[close_col].astype(float)
                    last_price = fetch_last_price(ticker)
                    seq, used_now = prepare_rsi_sequence(closes_5m, last_price, strict_window=True, period=RSI_PERIOD)
                    if seq is None:
                        out["5m"] = {"RSI": "-", "time": "-"}
                    else:
                        rsi_val = compute_rsi_wilder(seq, period=RSI_PERIOD)
                        # время: если использовали last_price — текущее МСК, иначе время последней 5m свечи +3h
                        if used_now:
                            last_time_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            last_idx = r5.index[-1]
                            last_ts = (last_idx + timedelta(hours=3))
                            last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
                        out["5m"] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}

    # ---------- 1h: напрямую ----------
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
            # parse times
            df1h[begin_col_h] = pd.to_datetime(df1h[begin_col_h], utc=True, errors="coerce")
            df1h = df1h.dropna(subset=[close_col_h])
            if df1h.empty:
                out["1h"] = {"RSI": "-", "time": "-"}
            else:
                closes_h = df1h[close_col_h].astype(float)
                last_price_h = fetch_last_price(ticker)
                seq_h, used_now_h = prepare_rsi_sequence(closes_h, last_price_h, strict_window=True, period=RSI_PERIOD)
                if seq_h is None:
                    out["1h"] = {"RSI": "-", "time": "-"}
                else:
                    rsi_h = compute_rsi_wilder(seq_h, period=RSI_PERIOD)
                    if used_now_h:
                        last_time_str_h = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        try:
                            last_ts = pd.to_datetime(df1h[begin_col_h].iloc[-1], utc=True)
                            last_ts_local = last_ts + timedelta(hours=3)
                            last_time_str_h = last_ts_local.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            last_time_str_h = "-"
                    out["1h"] = {"RSI": rsi_h if rsi_h is not None else "-", "time": last_time_str_h}

    return out

# --------------------- Фоновое обновление кэша ---------------------
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
            time.sleep(0.05)  # небольшой throttle, чтобы не бить MOEX
        with CACHE_LOCK:
            RSI_CACHE = new_cache
        # печать для отладки — можно закомментировать позднее
        print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Cache updated")
        time.sleep(REFRESH_SECONDS)

# --------------------- Маршруты ---------------------
@app.route("/api/rsi")
def api_rsi():
    with CACHE_LOCK:
        return jsonify(RSI_CACHE)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    # старт фонового потока
    threading.Thread(target=refresh_cache, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
