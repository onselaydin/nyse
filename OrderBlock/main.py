from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from ai.dataset_builder import DatasetBuilder
from ai.inference import AIInference
from config import get_config
from core.backtester import Backtester
from core.logger import setup_logger
from core.visualization import plot_equity_matplotlib, plot_equity_plotly, plot_price_structure
from mt5.connector import MT5Connector
from mt5.live_trader import MT5LiveTrader
from optimization.grid_search import run_grid_search
from optimization.optuna_search import run_optuna_search


def ensure_dirs(cfg) -> None:
    cfg.paths.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.dataset_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.ai_models_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.charts_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.logs_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.backtests_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.optimization_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.strategy_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.mt5_dir.mkdir(parents=True, exist_ok=True)


def fetch_or_load_data(cfg, logger, use_cached: bool) -> dict[str, pd.DataFrame]:
    symbol = cfg.strategy.symbol
    tfs = cfg.strategy.timeframes
    data_by_tf: dict[str, pd.DataFrame] = {}

    if use_cached:
        for tf in tfs:
            csv_path = cfg.paths.data_dir / f"{symbol}_{tf}.csv"
            if not csv_path.exists():
                raise FileNotFoundError(f"Cache veri dosyası yok: {csv_path}")
            df = pd.read_csv(csv_path)
            df["time"] = pd.to_datetime(df["time"], utc=True)
            data_by_tf[tf] = df
        return data_by_tf

    mt5_conn = MT5Connector(cfg, logger)
    if not mt5_conn.connect():
        raise RuntimeError("MT5 bağlantısı kurulamadı.")

    try:
        for tf in tfs:
            df = mt5_conn.fetch_rates(symbol=symbol, timeframe=tf, months=cfg.strategy.history_months)
            ok = mt5_conn.validate_missing_candles(df, tf)
            if not ok:
                logger.warning("Eksik mum oranı yüksek olabilir | TF=%s", tf)

            out = cfg.paths.data_dir / f"{symbol}_{tf}.csv"
            df.to_csv(out, index=False)
            logger.info("Veri kaydedildi: %s", out)
            data_by_tf[tf] = df
    finally:
        mt5_conn.shutdown()

    return data_by_tf


def run_backtest(cfg, logger, data_by_tf: dict[str, pd.DataFrame], use_ai: bool) -> None:
    bt = Backtester(cfg, logger)

    ai_inf = None
    if use_ai and cfg.ai.enabled:
        ai_inf = AIInference(cfg, logger)
        model_path = cfg.paths.ai_models_dir / "candle_cnn.pt"
        ai_inf.load_weights(model_path)

    summary_rows = []

    for tf in ["M15", "H1", "H4"]:
        result = bt.run_single_timeframe(
            timeframe=tf,
            exec_df=data_by_tf[tf],
            h1_df=data_by_tf["H1"],
            h4_df=data_by_tf["H4"],
            ai_inference=ai_inf,
        )

        metrics = result["metrics"]
        trades_df = result["trades_df"]
        candles_df = result["candles_df"]
        equity_curve = result["equity_curve"]

        trades_path = cfg.paths.backtests_dir / f"{tf}_trades.csv"
        trades_df.to_csv(trades_path, index=False)

        metrics_path = cfg.paths.backtests_dir / f"{tf}_metrics.csv"
        pd.DataFrame([asdict(metrics)]).to_csv(metrics_path, index=False)

        eq_path = cfg.paths.backtests_dir / f"{tf}_equity.csv"
        pd.DataFrame({"equity": equity_curve}).to_csv(eq_path, index=False)

        plot_equity_matplotlib(equity_curve, cfg.paths.charts_dir / f"{tf}_equity.png", f"{tf} Equity Curve")
        plot_equity_plotly(equity_curve, cfg.paths.charts_dir / f"{tf}_equity.html", f"{tf} Equity Curve")
        plot_price_structure(candles_df, trades_df, cfg.paths.charts_dir / f"{tf}_price_structure.html", f"{tf} Price")

        logger.info(
            "[%s] İşlem=%s | Net PnL=%.2f USD | Getiri=%.2f%% | WinRate=%.2f%%",
            tf,
            metrics.total_trades,
            metrics.total_pnl_usd,
            metrics.total_return_pct,
            metrics.win_rate,
        )

        summary_rows.append(
            {
                "timeframe": tf,
                "total_trades": metrics.total_trades,
                "wins": metrics.wins,
                "losses": metrics.losses,
                "pnl_usd": metrics.total_pnl_usd,
                "return_pct": metrics.total_return_pct,
                "win_rate": metrics.win_rate,
                "profit_factor": metrics.profit_factor,
                "max_drawdown_pct": metrics.max_drawdown_pct,
                "sharpe_ratio": metrics.sharpe_ratio,
                "buy_trades": metrics.buy_trades,
                "sell_trades": metrics.sell_trades,
                "consecutive_wins_max": metrics.consecutive_wins_max,
                "consecutive_losses_max": metrics.consecutive_losses_max,
            }
        )

    summary_df = pd.DataFrame(summary_rows)
    summary_path = cfg.paths.backtests_dir / "summary.csv"
    summary_df.to_csv(summary_path, index=False)

    total_pnl = float(summary_df["pnl_usd"].sum())
    total_ret = float(summary_df["return_pct"].sum())
    logger.info("GENEL ÖZET | Toplam Net PnL=%.2f USD | Toplam Getiri=%.2f%%", total_pnl, total_ret)


def run_optimization(cfg, logger, data_by_tf: dict[str, pd.DataFrame], optimizer: str) -> None:
    if optimizer == "grid":
        grid_df = run_grid_search(cfg, logger, data_by_tf)
        out = cfg.paths.optimization_dir / "grid_search_results.csv"
        grid_df.to_csv(out, index=False)
        logger.info("Grid search sonuçları kaydedildi: %s", out)
        return

    study = run_optuna_search(cfg, logger, data_by_tf)
    rows = [{"best_value": study.best_value, **study.best_params}]
    out = cfg.paths.optimization_dir / "optuna_best.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    logger.info("Optuna sonuçları kaydedildi: %s", out)


def run_dataset(cfg, logger, data_by_tf: dict[str, pd.DataFrame]) -> None:
    builder = DatasetBuilder(cfg, logger)
    paths = builder.build_multi_timeframe(data_by_tf)
    for p in paths:
        logger.info("Dataset metadata üretildi: %s", p)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OrderBlock AI Forex Research Sistemi")
    parser.add_argument("--mode", choices=["backtest", "dataset", "optimize", "live"], default="backtest")
    parser.add_argument("--optimizer", choices=["grid", "optuna"], default="optuna")
    parser.add_argument("--use-cached-data", action="store_true")
    parser.add_argument("--use-ai", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    cfg = get_config()
    ensure_dirs(cfg)
    logger = setup_logger(cfg.paths.logs_dir)

    args = parse_args()
    if args.mode == "live":
        trader = MT5LiveTrader(cfg, logger)
        if not trader.connect():
            raise RuntimeError("Canlı trader MT5 bağlantısı kurulamadı.")
        try:
            trader.run_loop(poll_seconds=args.poll_seconds)
        finally:
            trader.shutdown()
        return

    data_by_tf = fetch_or_load_data(cfg, logger, use_cached=args.use_cached_data)

    if args.mode == "dataset":
        run_dataset(cfg, logger, data_by_tf)
        return

    if args.mode == "optimize":
        run_optimization(cfg, logger, data_by_tf, optimizer=args.optimizer)
        return

    run_backtest(cfg, logger, data_by_tf, use_ai=args.use_ai)


if __name__ == "__main__":
    main()
