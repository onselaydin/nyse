import yfinance as yf
import pandas as pd
import numpy as np
import requests
from ta.momentum import RSIIndicator
import time
import os

# Telegram ayarları
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '5234788845:AAGRh1LfTx5KxBBCgI5wXk3Nd7hSLEOVE-E')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '-1001644944675')

SYMBOLS = ['VZ', 'OKE', 'FLNG', 'MO', 'ENB', 'PFE', 'STWD', 'NLY']
EXCHANGE_SUFFIX = ''  # NYSE için gerek yok, NASDAQ için .NS gibi ekler olurdu

# SMC pattern tespiti için yardımcı fonksiyonlar
def detect_smc(df):
    # HH, HL, LH, LL tespiti
    df = df.copy()
    df['HH'] = (df['High'] > df['High'].shift(1)) & (df['High'] > df['High'].shift(-1))
    df['LL'] = (df['Low'] < df['Low'].shift(1)) & (df['Low'] < df['Low'].shift(-1))
    # Trend tespiti (basit)
    df['trend'] = np.where(df['High'] > df['High'].shift(1), 'up', 'down')
    return df

def detect_bos(df):
    # Basit BOS: Son LL sonrası yeni bir HH oluşursa
    last_ll = df[df['LL']].index[-1] if df['LL'].any() else None
    if last_ll is not None:
        after_ll = df.loc[last_ll:]
        if (after_ll['High'] > df['High'].loc[last_ll]).any():
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
    rsi = RSIIndicator(df['Close'], window=14)
    df['RSI'] = rsi.rsi()
    msg = ''
    # HL ve uptrend ise
    if df['trend'].iloc[-1] == 'up' and df['Low'].iloc[-1] > df['Low'].iloc[-2]:
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
    for symbol in SYMBOLS:
        interval = choose_best_interval(symbol)
        msg = analyze_symbol(symbol, interval)
        if msg:
            send_telegram(msg)
        time.sleep(2)  # API limitine takılmamak için

if __name__ == '__main__':
    main()
