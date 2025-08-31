from flask import Flask, jsonify, send_from_directory
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta, timezone
import pandas as pd
import os

app = Flask(__name__, static_folder="static")

TOKEN = "t.a_yTo2QKdKX0FFwrNTmkvlKAfBml74hg7SVdW-GbyAVhY5znKubj2meA61ufoYGu_awUxQvozh07QHBrY3OgZA"

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

TIMEFRAMES = {
    "5m": CandleInterval.CANDLE_INTERVAL_5_MIN,
    "1h": CandleInterval.CANDLE_INTERVAL_HOUR
}

# Функция для расчета RSI
def compute_rsi(prices, period=14):
    if len(prices) < period:
        return None
    series = pd.Series(prices)
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    return round(rsi.iloc[-1], 2)

# Функция получения свечей с обработкой ошибок
def get_candles_safe(client, figi, interval, lookback_minutes):
    try:
        now = datetime.now(timezone.utc)
        candles = client.market_data.get_candles(
            figi=figi,
            from_=now - timedelta(minutes=lookback_minutes),
            to=now,
            interval=interval
        ).candles
        return candles
    except Exception as e:
        print(f"Ошибка запроса свечей {figi} ({interval}): {e}")
        return []

# Основная функция получения RSI по всем инструментам
def fetch_rsi_data():
    results = {}
    with Client(TOKEN) as client:
        for name, figi in INSTRUMENTS.items():
            results[name] = {}
            for tf_name, interval in TIMEFRAMES.items():
                # Безопасное ограничение lookback
                lookback = 500 if tf_name == "5m" else 200
                candles = get_candles_safe(client, figi, interval, lookback)
                
                if not candles or len(candles) < 15:
                    results[name][tf_name] = {"RSI": "-", "time": "-"}
                    continue

                prices = [c.close.units + c.close.nano / 1e9 for c in candles]
                
                # Подставляем актуальную цену последней свечи
                try:
                    last_price_resp = client.market_data.get_last_prices(figi=[figi])
                    if last_price_resp.last_prices:
                        current_price = (
                            last_price_resp.last_prices[0].price.units
                            + last_price_resp.last_prices[0].price.nano / 1e9
                        )
                        prices[-1] = current_price
                except:
                    pass

                rsi_val = compute_rsi(prices)
                last_time = candles[-1].time.astimezone(
                    timezone(timedelta(hours=3))
                ).strftime("%Y-%m-%d %H:%M:%S")
                results[name][tf_name] = {"RSI": rsi_val if rsi_val else "-", "time": last_time}
    return results

@app.route("/api/rsi")
def api_rsi():
    data = fetch_rsi_data()
    return jsonify(data)

@app.route("/")
def index():
    return send_from_directory(os.getcwd(), "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
