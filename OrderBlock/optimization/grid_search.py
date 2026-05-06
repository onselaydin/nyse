from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Any

import pandas as pd

from config import AppConfig
from core.backtester import Backtester


def run_grid_search(
    cfg: AppConfig,
    logger,
    data_by_tf: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    bt = Backtester(cfg, logger)

    rr_values = cfg.optimization.grid_rr_targets
    wick_values = cfg.optimization.grid_wick_ratios
    momentum_values = cfg.optimization.grid_momentum_thresholds
    ob_values = cfg.optimization.grid_ob_impulse_multipliers

    for rr, wick, mom, ob in itertools.product(rr_values, wick_values, momentum_values, ob_values):
        local_cfg = replace(cfg)
        local_cfg.risk.rr_targets = (float(rr),)
        local_cfg.strategy.wick_to_body_ratio_min = float(wick)
        local_cfg.strategy.momentum_body_to_range_min = float(mom)
        local_cfg.strategy.ob_impulse_multiplier = float(ob)

        total_pnl = 0.0
        total_ret = 0.0
        total_trades = 0

        for tf in ["M15", "H1", "H4"]:
            exec_df = data_by_tf[tf]
            result = bt.run_single_timeframe(
                timeframe=tf,
                exec_df=exec_df,
                h1_df=data_by_tf["H1"],
                h4_df=data_by_tf["H4"],
            )
            m = result["metrics"]
            total_pnl += m.total_pnl_usd
            total_ret += m.total_return_pct
            total_trades += m.total_trades

        records.append(
            {
                "rr": rr,
                "wick_ratio": wick,
                "momentum_ratio": mom,
                "ob_impulse_multiplier": ob,
                "total_pnl_usd": total_pnl,
                "total_return_pct": total_ret,
                "total_trades": total_trades,
            }
        )

    df = pd.DataFrame(records).sort_values("total_pnl_usd", ascending=False).reset_index(drop=True)
    return df
