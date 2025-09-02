# Периоды загрузки
LOOKBACK_DAYS = {
    "5m": 7,    # последние 7 дней для минуток
    "1h": 10,   # последние 10 дней для часов
}

def build_rsi_row_for_instrument(ticker):
    """Возвращает RSI по 5m и 1h"""
    out = {}

    # --- 5m (агрегация из 1m)
    df_1m = fetch_moex_candles(ticker, "1", LOOKBACK_DAYS["5m"])
    if df_1m is not None and not df_1m.empty:
        close_col = next((c for c in df_1m.columns if c.lower() == "close"), None)
        begin_col = next((c for c in df_1m.columns if c.lower() == "begin"), None)
        if close_col:
            # Агрегируем по 5 минут
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
            out["5m"] = {"RSI": rsi_val if rsi_val else "-", "time": last_time_str}
        else:
            out["5m"] = {"RSI": "-", "time": "-"}
    else:
        out["5m"] = {"RSI": "-", "time": "-"}

    # --- 1h
    df_1h = fetch_moex_candles(ticker, "60", LOOKBACK_DAYS["1h"])
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
            out["1h"] = {"RSI": rsi_val if rsi_val else "-", "time": last_time_str}
        else:
            out["1h"] = {"RSI": "-", "time": "-"}
    else:
        out["1h"] = {"RSI": "-", "time": "-"}

    return out
