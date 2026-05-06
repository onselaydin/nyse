from __future__ import annotations

from dataclasses import replace

import optuna
import pandas as pd

from config import AppConfig
from core.backtester import Backtester


def run_optuna_search(cfg: AppConfig, logger, data_by_tf: dict[str, pd.DataFrame]) -> optuna.Study:
    bt = Backtester(cfg, logger)

    def objective(trial: optuna.Trial) -> float:
        rr = trial.suggest_float("rr", 1.5, 3.5, step=0.5)
        wick_ratio = trial.suggest_float("wick_ratio", 1.0, 2.5, step=0.1)
        momentum_ratio = trial.suggest_float("momentum_ratio", 0.50, 0.85, step=0.05)
        ai_threshold = trial.suggest_float("ai_confidence_threshold", 0.50, 0.90, step=0.05)

        local_cfg = replace(cfg)
        local_cfg.risk.rr_targets = (rr,)
        local_cfg.strategy.wick_to_body_ratio_min = wick_ratio
        local_cfg.strategy.momentum_body_to_range_min = momentum_ratio
        local_cfg.ai.confidence_threshold = ai_threshold

        total_pnl = 0.0
        for tf in ["M15", "H1", "H4"]:
            res = bt.run_single_timeframe(
                timeframe=tf,
                exec_df=data_by_tf[tf],
                h1_df=data_by_tf["H1"],
                h4_df=data_by_tf["H4"],
            )
            total_pnl += res["metrics"].total_pnl_usd

        return total_pnl

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=cfg.optimization.optuna_trials)

    logger.info("Optuna en iyi skor: %.2f", study.best_value)
    logger.info("Optuna en iyi parametreler: %s", study.best_params)
    return study
