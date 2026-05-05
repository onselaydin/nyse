from __future__ import annotations

import itertools
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

from core.backtester import Backtester


class GridSearchOptimizer:
    """RR, pivot sensitivity ve FVG minimum boyutu için grid search optimizasyonu."""

    def __init__(
        self,
        project_root: Path,
        system_cfg: dict[str, Any],
        base_strategy_cfg: dict[str, Any],
        logger,
    ):
        self.project_root = project_root
        self.system_cfg = system_cfg
        self.base_strategy_cfg = base_strategy_cfg
        self.logger = logger

    def run(
        self,
        rr_values: list[float],
        pivot_values: list[int],
        fvg_values: list[int],
        symbol: str,
        timeframes: list[str],
        data_by_tf: dict[str, pd.DataFrame],
        h1_df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Tüm kombinasyonları test eder, skorlayıp en iyi konfigürasyonu döndürür."""

        rows: list[dict[str, Any]] = []

        combos = list(itertools.product(rr_values, pivot_values, fvg_values))
        self.logger.info("Grid search başlatıldı | Toplam kombinasyon: %s", len(combos))

        for rr_target, pivot_sensitivity, min_fvg_size_points in combos:
            strategy_cfg = deepcopy(self.base_strategy_cfg)

            # İstenen senaryo: HTF filtresi kapalı.
            strategy_cfg.setdefault("htf_filter", {})["enabled"] = False
            strategy_cfg.setdefault("risk", {})["rr_target"] = float(rr_target)
            strategy_cfg["pivot_sensitivity"] = int(pivot_sensitivity)
            strategy_cfg["min_fvg_size_points"] = int(min_fvg_size_points)

            # Optimizasyon sırasında gereksiz çıktı üretimini engelle.
            strategy_cfg.setdefault("feature_toggles", {})["save_charts"] = False

            backtester = Backtester(self.project_root, self.system_cfg, strategy_cfg, self.logger)

            total_pnl = 0.0
            total_trades = 0
            weighted_win_rate_sum = 0.0
            profit_factors = []
            max_drawdowns = []

            for tf in timeframes:
                result_pack = backtester.run(
                    symbol=symbol,
                    timeframe=tf,
                    df=data_by_tf[tf],
                    h1_df=h1_df,
                )
                result = result_pack["result"]

                total_pnl += float(result.total_pnl)
                total_trades += int(result.total_trades)
                weighted_win_rate_sum += float(result.win_rate) * int(result.total_trades)
                if result.profit_factor != float("inf"):
                    profit_factors.append(float(result.profit_factor))
                max_drawdowns.append(float(result.max_drawdown_pct))

            weighted_win_rate = (weighted_win_rate_sum / total_trades) if total_trades > 0 else 0.0
            avg_profit_factor = sum(profit_factors) / len(profit_factors) if profit_factors else 0.0
            worst_drawdown = max(max_drawdowns) if max_drawdowns else 0.0

            # Skor: PnL odaklı, yüksek DD için ceza, PF/WinRate katkısı.
            score = total_pnl - (worst_drawdown * 20.0) + (avg_profit_factor * 40.0) + (weighted_win_rate * 1.0)

            row = {
                "rr_target": float(rr_target),
                "pivot_sensitivity": int(pivot_sensitivity),
                "min_fvg_size_points": int(min_fvg_size_points),
                "total_pnl": round(total_pnl, 4),
                "total_trades": int(total_trades),
                "weighted_win_rate": round(weighted_win_rate, 4),
                "avg_profit_factor": round(avg_profit_factor, 6),
                "worst_drawdown_pct": round(worst_drawdown, 6),
                "score": round(score, 6),
            }
            rows.append(row)

            self.logger.info(
                "Grid aday | RR=%.2f pivot=%s fvg=%s | PnL=%.2f | Score=%.2f",
                rr_target,
                pivot_sensitivity,
                min_fvg_size_points,
                total_pnl,
                score,
            )

        results_df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
        best = results_df.iloc[0].to_dict()

        optimized_cfg = deepcopy(self.base_strategy_cfg)
        optimized_cfg.setdefault("htf_filter", {})["enabled"] = False
        optimized_cfg.setdefault("risk", {})["rr_target"] = float(best["rr_target"])
        optimized_cfg["pivot_sensitivity"] = int(best["pivot_sensitivity"])
        optimized_cfg["min_fvg_size_points"] = int(best["min_fvg_size_points"])

        return results_df, optimized_cfg

    def save_outputs(
        self,
        results_df: pd.DataFrame,
        optimized_cfg: dict[str, Any],
        csv_path: Path,
        json_path: Path,
    ) -> None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)

        results_df.to_csv(csv_path, index=False)
        json_path.write_text(json.dumps(optimized_cfg, indent=2), encoding="utf-8")

        self.logger.info("Grid search sonuçları kaydedildi: %s", csv_path)
        self.logger.info("Optimize konfigürasyon kaydedildi: %s", json_path)
