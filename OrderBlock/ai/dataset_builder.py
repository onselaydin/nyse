from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import AppConfig


class DatasetBuilder:
    def __init__(self, cfg: AppConfig, logger):
        self.cfg = cfg
        self.logger = logger

    def _label_rule(self, window: pd.DataFrame) -> str:
        last = window.iloc[-1]
        o, h, l, c = float(last["Open"]), float(last["High"]), float(last["Low"]), float(last["Close"])
        body = abs(c - o)
        rng = max(1e-10, h - l)

        if body / rng > 0.7 and c > o:
            return "strong_bullish_candle"
        if body / rng > 0.7 and c < o:
            return "strong_bearish_candle"

        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)

        if lower_wick / max(1e-10, body) >= self.cfg.strategy.wick_to_body_ratio_min:
            return "rejection_candle"
        if upper_wick / max(1e-10, body) >= self.cfg.strategy.wick_to_body_ratio_min:
            return "rejection_candle"

        return "bad_setup"

    def _save_window_image(self, window: pd.DataFrame, out_path: Path) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(2.4, 2.4))
        ax.plot(window["Close"].values, linewidth=1.2)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title("sample", fontsize=8)
        plt.tight_layout()
        fig.savefig(out_path, dpi=100)
        plt.close(fig)

    def build_from_dataframe(self, df: pd.DataFrame, timeframe: str, window_size: int = 20, step: int = 3) -> Path:
        dataset_root = self.cfg.paths.dataset_dir
        dataset_root.mkdir(parents=True, exist_ok=True)
        metadata_rows: list[dict] = []

        for i in range(window_size, len(df), step):
            window = df.iloc[i - window_size : i].copy()
            label = self._label_rule(window)
            if label not in self.cfg.ai.labels:
                continue

            label_dir = dataset_root / label
            sample_name = f"{timeframe}_{i:06d}.png"
            sample_path = label_dir / sample_name
            self._save_window_image(window, sample_path)

            metadata_rows.append(
                {
                    "timeframe": timeframe,
                    "index": i,
                    "label": label,
                    "image_path": str(sample_path),
                    "time": str(window.iloc[-1]["time"]),
                    "open": float(window.iloc[-1]["Open"]),
                    "high": float(window.iloc[-1]["High"]),
                    "low": float(window.iloc[-1]["Low"]),
                    "close": float(window.iloc[-1]["Close"]),
                }
            )

        metadata_path = dataset_root / f"metadata_{timeframe}.json"
        with metadata_path.open("w", encoding="utf-8") as f:
            json.dump(metadata_rows, f, ensure_ascii=False, indent=2)

        self.logger.info("Dataset üretildi | TF=%s | Örnek=%s | Metadata=%s", timeframe, len(metadata_rows), metadata_path)
        return metadata_path

    def build_multi_timeframe(self, dataframes: dict[str, pd.DataFrame]) -> list[Path]:
        out: list[Path] = []
        for tf, df in dataframes.items():
            out.append(self.build_from_dataframe(df=df, timeframe=tf))
        return out
