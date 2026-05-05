from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


class DataManager:
    """Veri ve konfigürasyon dosyalarının okunması/yazılması."""

    def __init__(self, project_root: Path, logger):
        self.project_root = project_root
        self.logger = logger

    def load_json_config(self, config_path: Path) -> dict[str, Any]:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self.logger.info("Konfigürasyon yüklendi: %s", config_path.name)
        return data

    def timeframe_months(self, timeframe: str, system_cfg: dict[str, Any]) -> int:
        """M5 için gerektiğinde daha kısa geçmiş kullanmaya imkan verir."""

        if timeframe == "M5":
            return int(system_cfg.get("m5_months_if_heavy", 1))
        return int(system_cfg.get("historical_months", 6))

    def resolve_date_range(self, timeframe: str, system_cfg: dict[str, Any]) -> tuple[datetime, datetime]:
        months = self.timeframe_months(timeframe, system_cfg)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=30 * months)
        return start_date, end_date

    def save_raw_data(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Path:
        data_dir = self.project_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        file_path = data_dir / f"{symbol}_{timeframe}.csv"
        df.to_csv(file_path, index=False)
        self.logger.info("Ham veri kaydedildi: %s", file_path)
        return file_path

    def load_raw_data(self, symbol: str, timeframe: str) -> pd.DataFrame:
        file_path = self.project_root / "data" / f"{symbol}_{timeframe}.csv"
        if not file_path.exists():
            raise FileNotFoundError(f"Veri dosyası bulunamadı: {file_path}")

        df = pd.read_csv(file_path)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df

    def save_dataframe(self, df: pd.DataFrame, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".csv":
            df.to_csv(output_path, index=False)
        elif output_path.suffix.lower() in {".xlsx", ".xls"}:
            df.to_excel(output_path, index=False)
        else:
            raise ValueError(f"Desteklenmeyen dosya uzantısı: {output_path.suffix}")

        self.logger.info("DataFrame kaydedildi: %s", output_path)
