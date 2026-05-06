from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd

from config import AppConfig


TIMEFRAME_MAP = {
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
}


@dataclass(slots=True)
class MT5Credentials:
    login: Optional[int]
    password: Optional[str]
    server: Optional[str]
    terminal_path: Optional[str]


class MT5Connector:
    """
    Sadece veri çekimi için güvenli MT5 bağlantı sınıfı.
    Mevcut çalışan EA/stratejilere müdahale etmez, order göndermez.
    """

    def __init__(self, cfg: AppConfig, logger):
        self.cfg = cfg
        self.logger = logger
        self.connected: bool = False

    def _read_credentials(self) -> MT5Credentials:
        mt5_cfg = self.cfg.mt5
        login_raw = os.getenv(mt5_cfg.login_env)
        login = int(login_raw) if login_raw and login_raw.isdigit() else None
        return MT5Credentials(
            login=login,
            password=os.getenv(mt5_cfg.password_env),
            server=os.getenv(mt5_cfg.server_env),
            terminal_path=os.getenv(mt5_cfg.path_env),
        )

    def connect(self) -> bool:
        creds = self._read_credentials()
        mt5_cfg = self.cfg.mt5

        for attempt in range(1, mt5_cfg.reconnect_attempts + 1):
            self.logger.info("MT5 bağlantı denemesi %s/%s", attempt, mt5_cfg.reconnect_attempts)

            init_kwargs = {}
            if creds.terminal_path:
                init_kwargs["path"] = creds.terminal_path

            initialized = mt5.initialize(**init_kwargs)
            if not initialized:
                self.logger.warning("MT5 initialize başarısız: %s", mt5.last_error())
                time.sleep(mt5_cfg.reconnect_wait_seconds)
                continue

            if creds.login and creds.password and creds.server:
                authorized = mt5.login(
                    login=creds.login,
                    password=creds.password,
                    server=creds.server,
                )
                if not authorized:
                    self.logger.warning("MT5 login başarısız: %s", mt5.last_error())
                    mt5.shutdown()
                    time.sleep(mt5_cfg.reconnect_wait_seconds)
                    continue

            terminal_info = mt5.terminal_info()
            account_info = mt5.account_info()
            self.connected = True
            self.logger.info(
                "MT5 bağlantı başarılı | Terminal=%s | Hesap=%s",
                terminal_info.name if terminal_info else "Bilinmiyor",
                account_info.login if account_info else "Bilinmiyor",
            )
            return True

        self.connected = False
        self.logger.error("MT5 bağlantısı kurulamadı.")
        return False

    def shutdown(self) -> None:
        if self.connected:
            mt5.shutdown()
            self.connected = False
            self.logger.info("MT5 bağlantısı kapatıldı.")

    def _ensure_connected(self) -> None:
        if not self.connected:
            raise RuntimeError("MT5 bağlı değil. Önce connect() çağrılmalı.")

    def fetch_rates(self, symbol: str, timeframe: str, months: int) -> pd.DataFrame:
        self._ensure_connected()
        if timeframe not in TIMEFRAME_MAP:
            raise ValueError(f"Desteklenmeyen timeframe: {timeframe}")

        utc_to = datetime.now(timezone.utc)
        utc_from = utc_to - timedelta(days=30 * months)

        rates = mt5.copy_rates_range(symbol, TIMEFRAME_MAP[timeframe], utc_from, utc_to)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"Veri çekilemedi: {symbol} {timeframe} | Hata={mt5.last_error()}")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "tick_volume": "Volume",
                "spread": "spread",
            },
            inplace=True,
        )
        df = df[["time", "Open", "High", "Low", "Close", "Volume", "spread"]].copy()
        df.sort_values("time", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def validate_missing_candles(self, df: pd.DataFrame, timeframe: str) -> bool:
        if df.empty:
            return False

        tf_minutes = {"M15": 15, "H1": 60, "H4": 240}[timeframe]
        expected_delta = pd.Timedelta(minutes=tf_minutes)

        deltas = df["time"].diff().dropna()
        missing = int((deltas > expected_delta).sum())
        ratio = missing / max(1, len(df) - 1)

        self.logger.info(
            "Eksik mum kontrolü | TF=%s | Eksik=%s | Oran=%.4f",
            timeframe,
            missing,
            ratio,
        )
        return ratio <= self.cfg.mt5.max_missing_candle_ratio
