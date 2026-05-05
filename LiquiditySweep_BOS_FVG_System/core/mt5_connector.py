from __future__ import annotations

from datetime import datetime
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd


TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


class MT5Connector:
    """MetaTrader 5 bağlantısı ve veri indirme işlemlerini yönetir."""

    def __init__(self, logger):
        self.logger = logger
        self.connected = False

    def connect(
        self,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        path: Optional[str] = None,
    ) -> bool:
        """MT5 terminaline bağlanır. Parametreler opsiyoneldir."""

        self.logger.info("MT5 bağlantısı başlatılıyor...")
        init_kwargs = {}
        if path:
            init_kwargs["path"] = path
        if login is not None:
            init_kwargs["login"] = login
        if password is not None:
            init_kwargs["password"] = password
        if server is not None:
            init_kwargs["server"] = server

        if not mt5.initialize(**init_kwargs):
            error = mt5.last_error()
            self.logger.error(f"MT5 bağlantısı başarısız: {error}")
            self.connected = False
            return False

        terminal_info = mt5.terminal_info()
        account_info = mt5.account_info()

        self.connected = True
        self.logger.info(
            "MT5 bağlantısı başarılı | Terminal: %s | Hesap: %s",
            terminal_info.name if terminal_info else "Bilinmiyor",
            account_info.login if account_info else "Demo/Bilinmiyor",
        )
        return True

    def shutdown(self) -> None:
        """MT5 bağlantısını güvenli şekilde kapatır."""

        if self.connected:
            mt5.shutdown()
            self.logger.info("MT5 bağlantısı kapatıldı.")
            self.connected = False

    def download_rates(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """Belirtilen sembol ve timeframe için OHLCV verisini indirir."""

        if timeframe not in TIMEFRAME_MAP:
            raise ValueError(f"Desteklenmeyen timeframe: {timeframe}")

        if not self.connected:
            raise RuntimeError("MT5 bağlı değil. Önce connect() çağırın.")

        self.logger.info(
            "Veri indiriliyor | Sembol: %s | TF: %s | Başlangıç: %s | Bitiş: %s",
            symbol,
            timeframe,
            start_date,
            end_date,
        )

        rates = mt5.copy_rates_range(
            symbol,
            TIMEFRAME_MAP[timeframe],
            start_date,
            end_date,
        )

        if rates is None or len(rates) == 0:
            error = mt5.last_error()
            self.logger.error(f"Veri alınamadı: {error}")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "tick_volume": "Volume",
            }
        )
        df = df[["time", "Open", "High", "Low", "Close", "Volume", "spread"]]
        df = df.sort_values("time").reset_index(drop=True)

        self.logger.info("İndirilen mum sayısı: %s", len(df))
        return df
