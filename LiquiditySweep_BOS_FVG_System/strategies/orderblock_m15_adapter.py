from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
ORDERBLOCK_ROOT = WORKSPACE_ROOT / "OrderBlock"
if str(ORDERBLOCK_ROOT) not in sys.path:
    sys.path.insert(0, str(ORDERBLOCK_ROOT))

from strategy.orderblock_strategy import OrderBlockStrategy


class OrderBlockM15Adapter:
    def __init__(self, logger):
        self.strategy = OrderBlockStrategy(_AdapterConfig(), logger)

    def process_bar(
        self,
        df: pd.DataFrame,
        i: int,
        market_context: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        context = market_context or {}
        h1_context = dict(context.get("h1") or {})
        h4_context = dict(context.get("h4") or {})

        signal = self.strategy.process_bar(df, i, h1_context, h4_context)
        if signal is None:
            return None

        candle_time = pd.Timestamp(df.iloc[i]["time"]).to_pydatetime()
        return {
            "time": candle_time,
            "side": signal.side,
            "entry_price": float(signal.entry_price),
            "stop_loss": float(signal.stop_loss),
            "take_profit": float(signal.take_profit),
            "reason": signal.reason,
        }


class _AdapterConfig:
    def __init__(self) -> None:
        self.strategy = _AdapterStrategyConfig()
        self.session = _AdapterSessionConfig()
        self.risk = _AdapterRiskConfig()


class _AdapterStrategyConfig:
    pivot_sensitivity = 2
    wick_to_body_ratio_min = 1.5
    momentum_body_to_range_min = 0.65
    min_displacement_points = 80.0
    allow_wick_confirmation = True
    allow_momentum_confirmation = True


class _AdapterRiskConfig:
    rr_targets = (2.0,)
    sl_buffer_points = 20.0


class _AdapterWindow:
    def __init__(self, start_hour_utc: int, end_hour_utc: int) -> None:
        self.start_hour_utc = start_hour_utc
        self.end_hour_utc = end_hour_utc


class _AdapterSessionConfig:
    enabled = True
    utc_offset_hours = 0
    london = _AdapterWindow(7, 11)
    new_york = _AdapterWindow(12, 16)
