# app.py — Flask backend (MOEX ISS, с автоопределением MOEX тикера по FIGI/TCS)
from flask import Flask, jsonify, send_from_directory
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import time
from functools import lru_cache
import os

app = Flask(__name__, static_folder="static")

# --- Тут оставь свой INSTRUMENTS (может быть FIGI/TCS или MOEX тикер) ---
INSTRUMENTS = {
    # примеры — можно оставить FIGI или MOEX тикер. Код автоматически постарается найти MOEX тикер.
    "Сбербанк": "BBG004730N88",
    "Газпром": "BBG004730RP0",
    "Лукойл": "BBG004730ZJ9",
    "Яндекс": "TCS00A107T19",
    # можно также прямо MOEX тикеры:
    # "Сбербанк (MOEX)": "SBER",
}

# Таймфреймы и lookback
TIMEFRAMES = {
    "5m": "5",
    "1h": "60",
}

LOOKBACK_DAYS = {
    "5m": 3,
    "1h": 60,
}

# --- Утилиты для работы с MOEX ISS ---

@lru_cache(maxsize=1)
def download_all_securities():
    """
    Скачивает таблицу securities.json один раз и кэширует.
    Возвращает tuple(columns_list, rows_list).
    """
    url = "https://iss.moex.com/iss/securities.json"
    try:
        r = requests.get(url, params={"iss.meta": "off"}, timeout=15)
        r.raise_for_status()
        payload = r.json()
        sec = payload.get("securities", {})
        cols = sec.get("columns", [])
        rows = sec.get("data", [])
        return cols, rows
    except Exception as e:
        print(f"[ISS] Ошибка при загрузке securities.json: {e}")
        return [], []

def find_moex_ticker_by_figi_or_uid(instrument_id):
    """
    Пытается найти MOEX SECID по FIGI/TCS/etc.
    Возвращает SECID (строка) или None.
    """
    if not instrument_id:
        return None

    # Если строка выглядит как обычный MOEX тикер (только буквы, длина <= 8), считаем, что это тикер
    # (на всякий случай приводим к верхнему регистру)
    s = str(instrument_id).strip()
    if s.isalpha() and len(s) <= 8:
        return s.upper()

    # Иначе ищем в securities.json по FIGI, ISIN, REGNUMBER, or INSTRUMENT_UID-like fields
    cols, rows = download_all_securities()
    if not cols or not rows:
        return None

    # создание словаря colname->index (lowercase)
    colmap = {c.lower(): i for i, c in enumerate(cols)}

    # потенциальные поля для сравнения
    candidates = []
    # FIGI
    if "figi" in colmap:
        candidates.append(("figi", colmap["figi"]))
    # instrument_id может соответствовать "secid"
    if "secid" in colmap:
        candidates.append(("secid", colmap["secid"]))
    # isin
    if "isin" in colmap:
        candidates.append(("isin", colmap["isin"]))
    # regnumber
    if "regnumber" in colmap:
        candidates.append(("regnumber", colmap["regnumber"]))
    # попробовать и другие поля, если есть
    # Ищем по строковому совпадению (case-insensitive)
    target = s.lower()
    for row in rows:
        try:
            for name, idx in candidates:
                cell = row[idx]
                if cell is None:
                    continue
                if str(cell).lower() == target:
                    # вернём SECID
                    if "secid" in colmap:
                        secid = row[colmap["secid"]]
                        if secid:
                            return str(secid).upper()
                    # если нет secid — возврат None
        except Exception:
            continue
    # если не нашли — возвращаем None
    return None

def fetch_moex_candles(ticker: str, interval: str, days: int):
    """
    Запрашивает candles.json у MOEX ISS для конкретного тикера.
    Возвращает DataFrame с колонками (case-insensitive) или None.
    """
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
    now = datetime.utcnow()
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    params = {"from": start, "till": end, "interval": interval}
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
        # ищем колонку CLOSE (case-insensitive)
        close_col = None
        for c in df.columns:
            if c.lower() == "close":
                close_col = c
                break
        if close_col is None:
            return None
        # приводим CLOSE к float
        try:
            df[close_col] = df[close_col].astype(float)
        except Exception:
            df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
        return df
    except Exception as e:
        # логируем и возвращаем None
        print(f"[ISS] error fetching candles for {ticker} interval={interval}: {e}")
        return None

def compute_rsi_from_list(prices, period=14):
    """RSI via pandas EWM. Возвращает float или None."""
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

def build_rsi_row_for_instrument(instrument_id_raw):
    """
    По исходному значению из INSTRUMENTS:
     - пытаемся взять MOEX тикер (если сырой — сразу)
     - иначе пробуем найти MOEX тикер по FIGI/ISIN/REGNUMBER
     - затем запрашиваем свечи и считаем RSI для всех TIMEFRAMES
    Возвращаем dict {tf: {"RSI": val_or "-", "time": str_or "-"}}
    """
    out = {}
    # возможные MOEX тикеры: если raw уже "SBER" — используем
    instrument_id = str(instrument_id_raw).strip()
    ticker_candidate = None

    # если уже похоже на MOEX тикер (буквы и длина <=8) — принимаем
    if instrument_id.isalpha() and len(instrument_id) <= 8:
        ticker_candidate = instrument_id.upper()
    else:
        # пытаемся найти MOEX тикер по FIGI/ISIN/REGNUMBER/т.п.
        ticker_candidate = find_moex_ticker_by_figi_or_uid(instrument_id)

    if ticker_candidate is None:
        # не смогли сопоставить — возвращаем '-' для всех TF
        for tf in TIMEFRAMES.keys():
            out[tf] = {"RSI": "-", "time": "-"}
        return out

    # для найденного тикера запрашиваем свечи для каждого TF
    for tf_name, interval in TIMEFRAMES.items():
        days = LOOKBACK_DAYS.get(tf_name, 30)
        df = fetch_moex_candles(ticker_candidate, interval, days)
        if df is None or df.empty:
            out[tf_name] = {"RSI": "-", "time": "-"}
            continue
        # найти имя колонки CLOSE и BEGIN (возможно 'begin' или 'BEGIN')
        close_col = next((c for c in df.columns if c.lower() == "close"), None)
        begin_col = next((c for c in df.columns if c.lower() == "begin"), None)
        if close_col is None:
            out[tf_name] = {"RSI": "-", "time": "-"}
            continue
        closes = list(df[close_col].astype(float).values)
        rsi_val = compute_rsi_from_list(closes)
        # время последней свечи
        last_time_str = "-"
        if begin_col:
            try:
                last_ts = pd.to_datetime(df[begin_col].iloc[-1])
                # если без tz — считаем как UTC и добавляем +3 часа (МСК)
                if last_ts.tzinfo is None:
                    last_ts = last_ts + timedelta(hours=3)
                else:
                    # приведение к МСК
                    last_ts = last_ts.tz_convert(timezone(timedelta(hours=3)))
                last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                last_time_str = str(df[begin_col].iloc[-1])
        out[tf_name] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}
        # небольшая задержка, чтобы не перегружать ISS
        time.sleep(0.02)
    return out

@app.route("/api/rsi")
def api_rsi():
    results = {}
    # Для всех инструментов собираем данные
    for name, instrument_id in INSTRUMENTS.items():
        try:
            results[name] = build_rsi_row_for_instrument(instrument_id)
        except Exception as e:
            print(f"[ERROR] {name} ({instrument_id}): {e}")
            results[name] = {tf: {"RSI": "-", "time": "-"} for tf in TIMEFRAMES.keys()}
    return jsonify(results)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    # Запускаем локально
    app.run(host="0.0.0.0", port=5000)
