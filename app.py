# app.py — MOEX ISS, корректная агрегация 1m -> 5m, RSI14 по последним 14 свечам (+актуальная цена)
from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import threading
import time

app = Flask(__name__, static_folder="static")

# инструменты (MOEX тикеры)
INSTRUMENTS = {
    "Сбербанк": "SBER",
    "Газпром": "GAZP",
    "Лукойл": "LKOH",
    "Яндекс": "YNDX",
}

LOOKBACK_DAYS = {
    "5m": 7,   # минуты: берем 1m за 7 дней и агрегируем в 5m
    "1h": 10,  # часы: берем 60m за 10 дней
}

RSI_PERIOD = 14
RSI_CACHE = {}
CACHE_LOCK = threading.Lock()

# --------------------- helper: загрузка свечей ---------------------
def fetch_moex_candles_df(ticker: str, interval: str, days: int):
    """
    Возвращает DataFrame с колонками как вернул MOEX (без приведения имён).
    interval: "1" или "60" (строка).
    """
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
    now = datetime.utcnow()
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"from": start, "till": now.strftime("%Y-%m-%d"), "interval": interval}
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
        print(f"[ISS] error fetching candles for {ticker} interval={interval}: {e}")
        return None

# --------------------- helper: последняя цена ---------------------
def fetch_last_price(ticker: str):
    """Пытаемся получить LAST цену из securities endpoint. Возвращаем float или None."""
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
        # найти колонку с last (может называться 'LAST' или 'last')
        for i, c in enumerate(cols):
            if str(c).lower() == "last":
                val = rows[0][i]
                if val is None:
                    return None
                return float(val)
        return None
    except Exception as e:
        print(f"[ISS] error fetching last price for {ticker}: {e}")
        return None

# --------------------- helper: подготовка последовательности для RSI ---------------------
def prepare_series_for_rsi(close_series: pd.Series, last_price, period=RSI_PERIOD):
    """
    close_series: pd.Series упорядоченный по времени (ascending), dtype numeric
    last_price: float or None
    Возвращает (list_of_prices, used_last_price_flag) либо (None, False) если недостаточно данных.
    Требование для расчёта: len(prices) >= period + 1
    Стратегия:
      - если есть last_price: берём последние `period` закрытий и добавляем last_price -> (period+1) значений
      - иначе: если в close_series >= period+1, берём последние period+1
    """
    vals = list(pd.to_numeric(close_series, errors='coerce').dropna())
    # пробуем вариант с last_price
    if last_price is not None:
        base = vals[-period:] if len(vals) >= period else vals[:]  # последние period или все
        cand = base + [last_price]
        if len(cand) >= period + 1:
            return cand, True
    # иначе пробуем последние period+1 закрытий
    if len(vals) >= period + 1:
        return vals[-(period + 1):], False
    # не хватает данных
    return None, False

# --------------------- RSI (Wilder-like via EWM alpha=1/period) ---------------------
def compute_rsi_from_list(prices_list, period=RSI_PERIOD):
    """
    prices_list: список чисел длины >= period+1.
    Возвращает float (округл. 2) или None.
    """
    try:
        s = pd.Series(prices_list, dtype="float64")
    except Exception:
        return None
    if len(s) < period + 1:
        return None
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

# --------------------- Основная логика: правильная агрегация 1m -> 5m и расчёт RSI ---------------------
def build_rsi_row_for_instrument(ticker: str):
    """
    Возвращает {"5m": {"RSI": val_or "-", "time": str}, "1h": {...}}
    """
    out = {}

    # ---- 5m: загружаем 1m, корректно агрегируем в 5T (5 минут) ----
    df1m = fetch_moex_candles_df(ticker, "1", LOOKBACK_DAYS["5m"])
    if df1m is None or df1m.empty:
        out["5m"] = {"RSI": "-", "time": "-"}
    else:
        # находим имена колонок case-insensitive
        colmap = {c.lower(): c for c in df1m.columns}
        if "close" not in colmap or "begin" not in colmap:
            out["5m"] = {"RSI": "-", "time": "-"}
        else:
            close_col = colmap["close"]
            begin_col = colmap["begin"]
            # datetime индекс
            df1m["begin_dt"] = pd.to_datetime(df1m[begin_col], errors="coerce")
            df1m = df1m.dropna(subset=["begin_dt"])
            if df1m.empty:
                out["5m"] = {"RSI": "-", "time": "-"}
            else:
                # Приведение к единому типу: удаляем tzinfo (MOEX возвращает UTC-ish; мы будем работать с naive UTC)
                if df1m["begin_dt"].dt.tz is not None:
                    df1m["begin_dt"] = df1m["begin_dt"].dt.tz_convert("UTC").dt.tz_localize(None)
                df1m = df1m.set_index("begin_dt").sort_index()
                # агрегируем в 5 минут — open/high/low/close: нам нужен только close (last)
                r = df1m.resample("5T", label="right", closed="right").agg({close_col: "last"})
                r = r.dropna(subset=[close_col])
                if r.empty:
                    out["5m"] = {"RSI": "-", "time": "-"}
                else:
                    closes_series = r[close_col].astype(float)
                    last_price = fetch_last_price(ticker)  # добавляем текущую цену, чтобы RSI был "живым"
                    base, used_now = prepare_series_for_rsi(closes_series, last_price, RSI_PERIOD)
                    if base is None:
                        out["5m"] = {"RSI": "-", "time": "-"}
                    else:
                        rsi_val = compute_rsi_from_list(base)
                        if used_now:
                            last_time_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            # берём индекс последней 5m свечи (она right-labeled)
                            last_idx = r.index[-1]
                            # last_idx — naive UTC index; переводим в МСК (UTC+3) для отображения
                            try:
                                last_ts = last_idx + timedelta(hours=3)
                                last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
                            except Exception:
                                last_time_str = str(last_idx)
                        out["5m"] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}

    # ---- 1h: прямой запрос interval=60 ----
    df1h = fetch_moex_candles_df(ticker, "60", LOOKBACK_DAYS["1h"])
    if df1h is None or df1h.empty:
        out["1h"] = {"RSI": "-", "time": "-"}
    else:
        colmap_h = {c.lower(): c for c in df1h.columns}
        if "close" not in colmap_h or "begin" not in colmap_h:
            out["1h"] = {"RSI": "-", "time": "-"}
        else:
            close_col_h = colmap_h["close"]
            begin_col_h = colmap_h["begin"]
            # сортировка
            try:
                df1h[begin_col_h] = pd.to_datetime(df1h[begin_col_h], errors="coerce")
            except Exception:
                pass
            df1h = df1h.dropna(subset=[close_col_h])
            if df1h.empty:
                out["1h"] = {"RSI": "-", "time": "-"}
            else:
                closes_series_h = df1h[close_col_h].astype(float)
                last_price_h = fetch_last_price(ticker)
                base_h, used_now_h = prepare_series_for_rsi(closes_series_h, last_price_h, RSI_PERIOD)
                if base_h is None:
                    out["1h"] = {"RSI": "-", "time": "-"}
                else:
                    rsi_val_h = compute_rsi_from_list(base_h)
                    if used_now_h:
                        last_time_str_h = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        # последнее время свечи
                        try:
                            last_ts = pd.to_datetime(df1h[begin_col_h].iloc[-1])
                            if last_ts.tzinfo is None:
                                last_ts = last_ts + timedelta(hours=3)
                            else:
                                last_ts = last_ts.tz_convert(timezone(timedelta(hours=3)))
                            last_time_str_h = last_ts.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            last_time_str_h = "-"
                    out["1h"] = {"RSI": rsi_val_h if rsi_val_h is not None else "-", "time": last_time_str_h}

    return out

# --------------------- фоновый кэш ---------------------
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
            time.sleep(0.05)  # небольшой throttle
        with CACHE_LOCK:
            RSI_CACHE = new_cache
        time.sleep(60)

# --------------------- маршруты ---------------------
@app.route("/api/rsi")
def api_rsi():
    with CACHE_LOCK:
        return jsonify(RSI_CACHE)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    threading.Thread(target=refresh_cache, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
