# app.py — MOEX ISS, RSI14 по 5m (агрегация из 1m) и 1h с учётом актуальной цены
from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import threading
import time

app = Flask(__name__, static_folder="static")

# Настройки
INSTRUMENTS = {
    "Сбербанк": "SBER",
    "Газпром": "GAZP",
    "Лукойл": "LKOH",
    "Яндекс": "YNDX",
}

# Сколько дней брать для исходных свечей (чтобы гарантировать достаточный запас)
LOOKBACK_DAYS = {
    "5m": 7,   # мы загружаем 1m свечи за 7 дней, потом агрегируем в 5m
    "1h": 10,  # часовые за 10 дней
}

RSI_PERIOD = 14  # RSI14
RSI_CACHE = {}
CACHE_LOCK = threading.Lock()

# === Вспомогательные функции ===

def fetch_moex_candles(ticker: str, interval: str, days: int):
    """
    Возвращает DataFrame с колонками как их вернул MOEX.
    interval: строка, например "1" или "60" (MOEX принимает числа, но мы передаём строкой).
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

def fetch_last_price(ticker: str):
    """
    Пытаемся получить актуальную цену (LAST) из securities endpoint.
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
        # ищем колонку, содержащую last / LAST
        idx = None
        for i, c in enumerate(cols):
            if str(c).lower() in ("last", "lastprice", "l"):
                idx = i
                break
        if idx is None:
            return None
        val = rows[0][idx]
        if val is None:
            return None
        return float(val)
    except Exception as e:
        # не фатально — вернём None
        print(f"[ISS] error fetching last price for {ticker}: {e}")
        return None

def compute_rsi_from_list(prices, period=RSI_PERIOD):
    """
    Ожидает список или pd.Series из чисел. Требует len >= period + 1.
    Возвращает float или None.
    """
    try:
        s = pd.Series(prices, dtype="float64")
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

# === Основная: строим RSI-строку для инструмента ===

def build_rsi_row_for_instrument(ticker: str):
    """
    Возвращает dict: {"5m": {"RSI": val_or "-", "time": str}, "1h": {...}}
    Алгоритм:
      - для 5m: загружаем 1m свечи, агрегируем каждые 5 => получаем 5m.
      - для 1h: загружаем 60-мин свечи.
      - берём последние RSI_PERIOD (14) закрытий; если хотим 'live' — добавляем last_price (текущую цену) в конец.
      - вычисляем RSI только если len >= period+1.
      - если last_price был добавлен — ставим time = текущее МСК время (потому что RSI "на сейчас").
    """
    out = {}

    # --- 5m: берем 1m и агрегируем
    df1m = fetch_moex_candles(ticker, "1", LOOKBACK_DAYS["5m"])
    if df1m is not None and not df1m.empty:
        # определить колонки
        close_col = next((c for c in df1m.columns if str(c).lower() == "close"), None)
        begin_col = next((c for c in df1m.columns if str(c).lower() == "begin"), None)
        if close_col is None:
            out["5m"] = {"RSI": "-", "time": "-"}
        else:
            # агрегируем в 5m: берём каждую 5-ю минутную свечу
            df5 = df1m.iloc[::5, :].reset_index(drop=True)
            try:
                closes_all = list(df5[close_col].astype(float).values)
            except Exception:
                closes_all = []
            # берем последние RSI_PERIOD закрытий
            base = closes_all[-RSI_PERIOD:] if len(closes_all) >= RSI_PERIOD else closes_all[:]
            used_now = False
            # попробуем подмешать последнюю цену для актуальности
            last_price = fetch_last_price(ticker)
            if last_price is not None:
                # добавляем как текущую цену (если это даст >= period+1)
                cand = list(base)
                cand.append(last_price)
                if len(cand) >= RSI_PERIOD + 1:
                    base = cand
                    used_now = True
            # если всё ещё недостаточно — попробуем расширить базу предыдущими закрытиями (если есть)
            if len(base) < RSI_PERIOD + 1:
                # попробуем взять более длинную историю из df5
                base_full = closes_all
                if len(base_full) >= RSI_PERIOD + 1:
                    base = base_full[-(RSI_PERIOD + 1):]
            rsi_val = compute_rsi_from_list(base) if len(base) >= RSI_PERIOD + 1 else None
            # время: если использовали текущую цену — показываем текущее МСК время, иначе — время последней свечи
            if used_now:
                last_time_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
            else:
                if begin_col and not df5.empty:
                    try:
                        last_ts = pd.to_datetime(df5[begin_col].iloc[-1])
                        if last_ts.tzinfo is None:
                            last_ts += timedelta(hours=3)
                        else:
                            last_ts = last_ts.tz_convert(timezone(timedelta(hours=3)))
                        last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        last_time_str = "-"
                else:
                    last_time_str = "-"
            out["5m"] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}
    else:
        out["5m"] = {"RSI": "-", "time": "-"}

    # --- 1h: напрямую
    df1h = fetch_moex_candles(ticker, "60", LOOKBACK_DAYS["1h"])
    if df1h is not None and not df1h.empty:
        close_col = next((c for c in df1h.columns if str(c).lower() == "close"), None)
        begin_col = next((c for c in df1h.columns if str(c).lower() == "begin"), None)
        if close_col is None:
            out["1h"] = {"RSI": "-", "time": "-"}
        else:
            try:
                closes_all = list(df1h[close_col].astype(float).values)
            except Exception:
                closes_all = []
            # берём последние RSI_PERIOD закрытий
            base = closes_all[-RSI_PERIOD:] if len(closes_all) >= RSI_PERIOD else closes_all[:]
            used_now = False
            last_price = fetch_last_price(ticker)
            if last_price is not None:
                cand = list(base)
                cand.append(last_price)
                if len(cand) >= RSI_PERIOD + 1:
                    base = cand
                    used_now = True
            if len(base) < RSI_PERIOD + 1:
                base_full = closes_all
                if len(base_full) >= RSI_PERIOD + 1:
                    base = base_full[-(RSI_PERIOD + 1):]
            rsi_val = compute_rsi_from_list(base) if len(base) >= RSI_PERIOD + 1 else None
            if used_now:
                last_time_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
            else:
                if begin_col and not df1h.empty:
                    try:
                        last_ts = pd.to_datetime(df1h[begin_col].iloc[-1])
                        if last_ts.tzinfo is None:
                            last_ts += timedelta(hours=3)
                        else:
                            last_ts = last_ts.tz_convert(timezone(timedelta(hours=3)))
                        last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        last_time_str = "-"
                else:
                    last_time_str = "-"
            out["1h"] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}
    else:
        out["1h"] = {"RSI": "-", "time": "-"}

    return out

# === Фоновое обновление кэша (один поток) ===
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
            # маленькая задержка, чтоб не травить MOEX (защита от burst)
            time.sleep(0.05)
        with CACHE_LOCK:
            RSI_CACHE = new_cache
        # обновляем каждую минуту
        time.sleep(60)

# === Маршруты ===
@app.route("/api/rsi")
def api_rsi():
    with CACHE_LOCK:
        return jsonify(RSI_CACHE)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    # стартуем фоновый поток и Flask
    threading.Thread(target=refresh_cache, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
