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
    "ПАО «КАЗАНЬОРГСИНТЕЗ» — акции привилегированные": "BBG0029SG1C1",
    "Ленэнерго": "BBG000NLC9Z6",
    "РусГидро": "BBG00475K2X9",
    "Ростелеком — привилегированные акции": "BBG004S685M3",
    "Yandex": "TCS00A107T19",
    "АФК Система": "BBG004S68614",
    "ТНС энерго Воронеж": "BBG000BX7DH0",
    "Банк ВТБ": "BBG004730ZJ9",
    "Роснефть": "BBG004731354",
    "Нижнекамскнефтехим": "BBG000GQSRR5",
    "En+ Group": "BBG000RMWQD4",
    "ЧМК": "BBG000RP8V70",
    "ФСК ЕЭС": "BBG00475JZZ6",
    "Газпром": "BBG004730RP0",
    "Саратовский НПЗ — акции привилегированные": "BBG002B2J5X0",
    "Распадская": "BBG004S68696",
    "Аптечная сеть 36,6": "BBG000K3STR7",
    "Северсталь": "BBG00475K6C3",
    "Сбербанк России — привилегированные акции": "BBG0047315Y7",
    "МРСК Волги": "BBG000PKWCQ7",
    "АЛРОСА": "BBG004S68B31",
    "Селигдар": "BBG002458LF8",
    "Группа Черкизово": "BBG000RTHVK7",
    "Русская аквакультура": "BBG000W325F7",
    "Мосэнерго": "BBG004S687W8",
    "Татнефть — привилегированные акции": "BBG004S68829",
    "Сургутнефтегаз": "BBG0047315D0",
    "Калужская сбытовая компания": "BBG000DBD6F6",
    "ТГК-1": "BBG000QFH687",
    "РуссНефть": "BBG00F9XX7H4",
    "САФМАР": "BBG003LYCMB1",
    "Акрон": "BBG004S688G4",
    "Магнит": "BBG004RVFCY3",
    "РусАгро": "TCS90A0JQUZ6",
    "КАМАЗ": "BBG000LNHHJ9",
    "Лензолото": "BBG000SK7JS5",
    "Вторая генерирующая компания оптового рынка электроэнергии": "BBG000RK52V1",
    "МРСК Центра и Приволжья": "BBG000VG1034",
    "ЛУКОЙЛ": "BBG004731032",
    "Полюс Золото": "BBG000R607Y3",
    "Банк Санкт-Петербург": "BBG000QJW156",
    "Татнефть": "BBG004RVFFC0",
    "ЮУНК": "BBG002YFXL29",
    "Пермэнергосбыт — акции привилегированные": "BBG000MZL2S9",
    "Ростелеком": "BBG004S682Z6",
    "TCS Group": "TCS80A107UL4",
    "ВСМПО-АВИСМА": "BBG004S68CV8",
    "МГТС — акции привилегированные": "BBG000PZ0833",
    "М.видео": "BBG004S68CP5",
    "Сбербанк России": "BBG004730N88",
    "Русолово": "BBG004Z2RGW8",
    "ПИК": "BBG004S68BH6",
    "ФосАгро": "BBG004S689R0",
    "НЛМК": "BBG004S681B4",
    "СОЛЛЕРС": "BBG004S68JR8",
    "Объединенная авиастроительная корпорация": "BBG000Q7ZZY2",
    "ТГК-14": "BBG000RG4ZQ4",
    "Транснефть": "BBG00475KHX6",
    "МТС": "BBG004S681W1",
    "Красный Октябрь": "BBG000NLB2G3",
    "Группа ЛСР": "BBG004S68C39",
    "Сургутнефтегаз — привилегированные акции": "BBG004S681M2",
    "НМТП": "BBG004S68BR5",
    "Магнитогорский металлургический комбинат": "BBG004S68507",
    "Ленэнерго — акции привилегированные": "BBG000NLCCM3",
    "Газпром нефть": "BBG004S684M6",
    "Нижнекамскнефтехим — акции привилегированные": "BBG000GQSVC2",
    "ДЭК": "BBG000V07CB8",
    "Наука-Связь": "BBG002BCQK67",
    "ТГК-2 — акции привилегированные": "BBG000Q7GJ60",
    "НОВАТЭК": "BBG00475KKY8",
    "Мечел": "BBG004S68598",
    "РКК Энергия им.С.П.Королева": "BBG000LWNRP3",
    "Лента": "BBG0063FKTD9",
    "МРСК Сибири": "BBG000VJMH65",
    "МРСК Юга": "BBG000C7P5M7",
    "ОВК": "TCS90A0JVBT9",
    "Пермэнергосбыт": "BBG000MZL0Y6",
    "Белуга Групп ПАО ао": "BBG000TY1CD1",
    "ДВМП": "BBG000QF1Q17",
    "МКБ": "BBG009GSYN76",
    "Мостотрест": "BBG004S68DD6",
    "НКХП": "BBG00BGKYH17",
    "МРСК Центра": "BBG000VH7TZ8",
    "Центральный Телеграф — акции привилегированные": "BBG0027F0Y27",
    "Интер РАО ЕЭС": "BBG004S68473",
    "Центральный Телеграф": "BBG000BBV4M5",
    "Аэрофлот": "BBG004S683W7",
    "ГДР X5 RetailGroup": "TCS03A108X38",
    "АбрауДюрсо": "BBG002W2FT69",
    "Фонд крупнейшие компании РФ": "TCS60A101X76",
    "Фонд золото": "IE00B8XB7377",
    "Фонд государственные облигации": "TCS70A10A1L8",
    "Фонд Российские облигации": "TCS60A1039N1",
    "Фонд пассивный доход": "TCS00A108WX3",
    "Фонд вечный портфель": "BBG000000001",
    "Фонд локальные валютные облигации": "TCS20A107597",
    "Ренессанс": "BBG00QKJSX05",
    "ГК Самолёт": "BBG00F6NKQX3",
    "Южуралзолото ГК": "TCS00A0JPP37",
    "Делимобиль": "TCS00A107J11",
    "ВК": "TCS00A106YF0",
    "Циан": "TCS00A10ANA1",
    "Куйбышев Азот": "BBG002B9MYC1",
    "Сегежа": "BBG0100R9963",
    "Элемент": "TCS50A102093",
    "ФСК Россети": "BBG00475JZZ6",
    "РБК": "TCS10A0JR6A6",
    "Совкомфлот": "BBG000R04X57",
    "Европлан": "TCS00A0ZZFS9",
    "СПБ биржа": "TCS60A0JQ9P9",
    "Эталон групп": "TCS50A10C1L6",
    "Белон": "TCS20A0J2QG8",
    "Новабев": "BBG000TY1CD1",
    "HENDERSON": "TCS00A106XF2",
    "Россети центр": "BBG000VH7TZ8",
    "Совкомбанк": "TCS00A0ZZAC4",
    "ГТМ": "TCS03A0ZYD22",
    "ВсеИнструменты": "TCS10A108K09",
    "МТС Банк": "TCS00A0JRH43",
    "ИНАРКТИКА": "BBG000W325F7",
    "КарМани": "TCS00A105NV2",
    "Кристалл": "TCS00A107KX0",
    "OZON": "BBG00Y91R9T3",
    "Завод ДИОД": "BBG000G25P51",
    "АСТРА": "RU000A106T36",
    "Аптеки": "BBG000K3STR7",
    "Фармсинтез": "TCS10A0JR514",
    "ЯТЭК": "BBG002B298N6",
    "ЭЛ-5 энерго": "BBG000F6YPH8",
    "МГКЛ": "TCS00A0JVJQ8",
    "Мать и дитя": "TCS00Y3XYV94",
    "Хэдхантер": "TCS20A107662",
    "Озон фарма": "TCS00A109B25"
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
    interval: строка, может быть '1', '60'
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
        return df
    except Exception as e:
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
    Возвращает dict с RSI по 5м и 1ч таймфреймам.
    """
    out = {}
    instrument_id = str(instrument_id_raw).strip()

    # ищем тикер
    if instrument_id.isalpha() and len(instrument_id) <= 8:
        ticker_candidate = instrument_id.upper()
    else:
        ticker_candidate = find_moex_ticker_by_figi_or_uid(instrument_id)

    if ticker_candidate is None:
        for tf in TIMEFRAMES.keys():
            out[tf] = {"RSI": "-", "time": "-"}
        return out

    # --- 5m: агрегируем из минуток (interval=1)
    df_1m = fetch_moex_candles(ticker_candidate, "1", LOOKBACK_DAYS["5m"])
    if df_1m is not None and not df_1m.empty:
        close_col = next((c for c in df_1m.columns if c.lower() == "close"), None)
        begin_col = next((c for c in df_1m.columns if c.lower() == "begin"), None)
        if close_col:
            # берём каждую 5-ю свечу как 5m
            df_5m = df_1m.iloc[::5, :].reset_index(drop=True)
            closes = list(df_5m[close_col].astype(float).values)
            rsi_val = compute_rsi_from_list(closes)
            last_time_str = "-"
            if begin_col:
                try:
                    last_ts = pd.to_datetime(df_5m[begin_col].iloc[-1])
                    if last_ts.tzinfo is None:
                        last_ts = last_ts + timedelta(hours=3)
                    else:
                        last_ts = last_ts.tz_convert(timezone(timedelta(hours=3)))
                    last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    last_time_str = str(df_5m[begin_col].iloc[-1])
            out["5m"] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}
        else:
            out["5m"] = {"RSI": "-", "time": "-"}
    else:
        out["5m"] = {"RSI": "-", "time": "-"}

    # --- 1h: берём напрямую (interval=60)
    df_1h = fetch_moex_candles(ticker_candidate, "60", LOOKBACK_DAYS["1h"])
    if df_1h is not None and not df_1h.empty:
        close_col = next((c for c in df_1h.columns if c.lower() == "close"), None)
        begin_col = next((c for c in df_1h.columns if c.lower() == "begin"), None)
        if close_col:
            closes = list(df_1h[close_col].astype(float).values)
            rsi_val = compute_rsi_from_list(closes)
            last_time_str = "-"
            if begin_col:
                try:
                    last_ts = pd.to_datetime(df_1h[begin_col].iloc[-1])
                    if last_ts.tzinfo is None:
                        last_ts = last_ts + timedelta(hours=3)
                    else:
                        last_ts = last_ts.tz_convert(timezone(timedelta(hours=3)))
                    last_time_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    last_time_str = str(df_1h[begin_col].iloc[-1])
            out["1h"] = {"RSI": rsi_val if rsi_val is not None else "-", "time": last_time_str}
        else:
            out["1h"] = {"RSI": "-", "time": "-"}
    else:
        out["1h"] = {"RSI": "-", "time": "-"}

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




