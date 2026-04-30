
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
now = datetime.datetime.now(istanbul)
current_time = now.time()

# NYSE açık saatleri (yaz saati için)
open_time = datetime.time(16, 30)
close_time = datetime.time(23, 0)

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
    df = yf.download(symbol, period='6mo', interval=interval)
    if df.empty or len(df) < 30:
        return None
    df = detect_smc(df)
    rsi = RSIIndicator(df['Close'].squeeze(), window=14)
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
    return msg if msg else None

def choose_best_interval(symbol):
    # 4h ve 1d için sinyal sıklığına bak
    signals = {}
    for interval in ['4h', '1d']:
        df = yf.download(symbol, period='6mo', interval=interval)
        if df.empty or len(df) < 30:
            continue
        df = detect_smc(df)
        rsi = RSIIndicator(df['Close'].squeeze(), window=14)
        df['RSI'] = rsi.rsi()
        count = 0
        if (df['trend'] == 'up').sum() > 5:
            count += 1
        if (df['RSI'] < 30).sum() > 0:
            count += 1
        signals[interval] = count
    return max(signals, key=signals.get) if signals else '1d'

def main():
    if not (open_time <= current_time <= close_time):
        print("Borsa kapalı, çıkılıyor.")
        sys.exit()
    for symbol in SYMBOLS:
        interval = choose_best_interval(symbol)
        msg = analyze_symbol(symbol, interval)
        if msg:
            send_telegram(msg)
        time.sleep(2)  # API limitine takılmamak için

if __name__ == '__main__':
    main()
