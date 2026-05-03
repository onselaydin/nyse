
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from ta.momentum import RSIIndicator
import os
import datetime
import pytz
import sys
import time

# Telegram ayarları
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

SYMBOLS = ['VZ', 'OKE', 'FLNG', 'MO', 'ENB', 'PFE', 'STWD', 'NLY']
EXCHANGE_SUFFIX = ''  # NYSE için gerek yok, NASDAQ için .NS gibi ekler olurdu


# Türkiye saat dilimi
istanbul = pytz.timezone('Europe/Istanbul')

# NYSE açık saatleri (yaz saati için)
open_time = datetime.time(16, 30)
close_time = datetime.time(23, 0)

def download_prices(symbol, interval):
    """Fetch price data with interval-safe periods and graceful fallback for empty responses."""
    period = '60d' if interval == '4h' else '6mo'
    try:
        df = yf.download(
            symbol,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
            threads=False,
        )
    except Exception as exc:
        print(f"{symbol} ({interval}) download error: {exc}")
        return pd.DataFrame()

    if df is None or df.empty:
        # Retry once with a different period to handle transient/provider-side quirks.
        fallback_period = '3mo' if interval == '4h' else '1y'
        try:
            df = yf.download(
                symbol,
                period=fallback_period,
                interval=interval,
                progress=False,
                auto_adjust=False,
                threads=False,
            )
        except Exception:
            return pd.DataFrame()

    if df is None or df.empty:
        # Second data path: Ticker().history can succeed when download endpoint is flaky.
        history_period = '3mo' if interval == '4h' else '6mo'
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(
                period=history_period,
                interval=interval,
                auto_adjust=False,
                actions=False,
            )
        except Exception:
            return pd.DataFrame()

    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()

def get_1d_price_series(df, column_name):
    """Return a 1D numeric Series for a price column, handling MultiIndex/2D outputs."""
    if isinstance(df.columns, pd.MultiIndex):
        if column_name not in df.columns.get_level_values(0):
            return None
        data = df.xs(column_name, axis=1, level=0)
    else:
        if column_name not in df.columns:
            return None
        data = df[column_name]

    if isinstance(data, pd.DataFrame):
        if data.empty:
            return None
        data = data.iloc[:, 0]

    return pd.to_numeric(data, errors='coerce')

def normalize_ohlc(df):
    """Create a clean OHLC frame with guaranteed 1D numeric columns."""
    normalized = pd.DataFrame(index=df.index)
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        series = get_1d_price_series(df, col)
        if series is not None:
            normalized[col] = series
    return normalized.dropna(subset=['High', 'Low', 'Close'])

# SMC pattern tespiti için yardımcı fonksiyonlar
def detect_smc(df):
    # HH, HL, LH, LL tespiti
    df = df.copy()
    df['HH'] = (df['High'] > df['High'].shift(1)) & (df['High'] > df['High'].shift(-1))
    df['LL'] = (df['Low'] < df['Low'].shift(1)) & (df['Low'] < df['Low'].shift(-1))
    # Trend tespiti (basit)
    df['trend'] = np.where(df['High'] > df['High'].shift(1), 'up', 'down').ravel().astype(object)
    return df

def detect_bos(df):
    # Basit BOS: Son LL sonrası yeni bir HH oluşursa
    last_ll = df[df['LL']].index[-1] if df['LL'].any() else None
    if last_ll is not None:
        after_ll = df.loc[last_ll:]
        ref_high = df['High'].loc[last_ll]
        if hasattr(ref_high, 'item'):
            ref_high = ref_high.item()
        result = (after_ll['High'] > ref_high)
        if hasattr(result, 'any'):
            result = result.any()
        if hasattr(result, 'item'):
            result = result.item()
        if not after_ll['High'].empty and result:
            return True
    return False

def send_telegram(msg):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg}
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print('Telegram error:', e)

def analyze_symbol(symbol, interval):
    df = download_prices(symbol, interval)
    if df.empty:
        return None, 'no_data'
    df = normalize_ohlc(df)
    if df.empty or len(df) < 30:
        return None, 'no_data'
    df = detect_smc(df)
    rsi = RSIIndicator(df['Close'], window=14)
    df['RSI'] = rsi.rsi()
    msg = ''
    # HL ve uptrend ise
    low_last = df['Low'].iloc[-1]
    low_prev = df['Low'].iloc[-2]
    if hasattr(low_last, 'item'):
        low_last = low_last.item()
    if hasattr(low_prev, 'item'):
        low_prev = low_prev.item()
    if df['trend'].iloc[-1] == 'up' and low_last > low_prev:
        msg += f'{symbol} ({interval}): HL oluştu, uptrend devam. Alım fırsatı olabilir.\n'
    # BOS yukarı
    if detect_bos(df):
        msg += f'{symbol} ({interval}): BOS yukarı, trend değişimi!\n'
    # RSI 30 altı
    if df['RSI'].iloc[-1] < 30:
        msg += f'{symbol} ({interval}): RSI < 30, dipte olabilir!\n'
    return (msg if msg else None), ('signal' if msg else 'no_signal')

def choose_best_interval(symbol):
    # 4h ve 1d için sinyal sıklığına bak
    signals = {}
    for interval in ['4h', '1d']:
        df = download_prices(symbol, interval)
        if df.empty:
            continue
        df = normalize_ohlc(df)
        if df.empty or len(df) < 30:
            continue
        df = detect_smc(df)
        rsi = RSIIndicator(df['Close'], window=14)
        df['RSI'] = rsi.rsi()
        count = 0
        if (df['trend'] == 'up').sum() > 5:
            count += 1
        if (df['RSI'] < 30).sum() > 0:
            count += 1
        signals[interval] = count
    return max(signals, key=signals.get) if signals else '1d'

def main():
    now = datetime.datetime.now(istanbul)
    current_time = now.time()

    print(f"Tarama basladi: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if not (open_time <= current_time <= close_time):
        print("Borsa kapali, cikiliyor.")
        sys.exit()

    signal_count = 0
    no_signal_count = 0
    no_data_count = 0

    for symbol in SYMBOLS:
        interval = choose_best_interval(symbol)
        msg, status = analyze_symbol(symbol, interval)
        if msg:
            send_telegram(msg)
            signal_count += 1
            print(f"{symbol}: sinyal gonderildi ({interval})")
        elif status == 'no_data':
            no_data_count += 1
            print(f"{symbol}: veri yok/eksik ({interval}), atlandi")
        else:
            no_signal_count += 1
            print(f"{symbol}: sinyal yok ({interval})")
        time.sleep(2)  # API limitine takılmamak için

    print(
        f"Tarama tamamlandi. Toplam: {len(SYMBOLS)}, "
        f"sinyal: {signal_count}, sinyal yok: {no_signal_count}, veri yok: {no_data_count}"
    )

if __name__ == '__main__':
    main()
