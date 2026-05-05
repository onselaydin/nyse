from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """EMA hesaplar."""

    return series.ewm(span=period, adjust=False).mean()


def candle_body_points(df: pd.DataFrame) -> pd.Series:
    """Mum gövde büyüklüğünü point cinsinden döndürür."""

    return (df["Close"] - df["Open"]).abs() * 100000
