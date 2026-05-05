from __future__ import annotations

import argparse
import os
from pathlib import Path

from rich.console import Console

from core.backtester import Backtester
from core.chart_renderer import ChartRenderer
from core.data_manager import DataManager
from core.logger import setup_logger
from core.mt5_connector import MT5Connector
from core.report_generator import ReportGenerator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Liquidity Sweep + BOS + FVG backtest sistemi"
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=str(Path(__file__).resolve().parent),
        help="Proje kök klasörü",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="MT5 indirme adımını atla, mevcut CSV verilerini kullan",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Sadece veri indir, backtest çalıştırma",
    )
    parser.add_argument(
        "--strategy-config",
        type=str,
        default="config/strategy_config.json",
        help="Kullanılacak strateji konfigürasyon dosya yolu (proje köküne göre)"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(args.project_root).resolve()

    logger = setup_logger(project_root / "logs")
    console = Console()
    dm = DataManager(project_root, logger)

    system_cfg = dm.load_json_config(project_root / "config" / "system_config.json")
    strategy_cfg_path = project_root / args.strategy_config
    strategy_cfg = dm.load_json_config(strategy_cfg_path)

    symbol = system_cfg["symbol"]
    timeframes = system_cfg["timeframes"]

    connector = MT5Connector(logger)

    if not args.skip_download:
        login = os.getenv("MT5_LOGIN")
        password = os.getenv("MT5_PASSWORD")
        server = os.getenv("MT5_SERVER")
        terminal_path = os.getenv("MT5_PATH")

        connected = connector.connect(
            login=int(login) if login else None,
            password=password,
            server=server,
            path=terminal_path,
        )
        if not connected:
            logger.error("MT5 bağlantısı yok. İndirme adımı yapılamadı.")
            return

        try:
            needed_tfs = sorted(set(timeframes + ["H1"]))
            for tf in needed_tfs:
                start_date, end_date = dm.resolve_date_range(tf, system_cfg)
                df = connector.download_rates(symbol, tf, start_date, end_date)
                if df.empty:
                    logger.warning("Boş veri geldi, timeframe atlanıyor: %s", tf)
                    continue
                dm.save_raw_data(symbol, tf, df)
        finally:
            connector.shutdown()

    if args.download_only:
        logger.info("Sadece veri indirme tamamlandı.")
        return

    h1_df = dm.load_raw_data(symbol, "H1")

    backtester = Backtester(project_root, system_cfg, strategy_cfg, logger)
    reporter = ReportGenerator(project_root, logger)
    renderer = ChartRenderer(project_root, logger)

    all_results = []

    for tf in timeframes:
        df = dm.load_raw_data(symbol, tf)
        result_pack = backtester.run(symbol=symbol, timeframe=tf, df=df, h1_df=h1_df)
        all_results.append(result_pack)

        tf_prefix = project_root / "results" / f"{symbol}_{tf}"
        result_pack["trades_df"].to_csv(f"{tf_prefix}_trades.csv", index=False)
        result_pack["swings_df"].to_csv(f"{tf_prefix}_swings.csv", index=False)
        result_pack["fvg_df"].to_csv(f"{tf_prefix}_fvg.csv", index=False)
        result_pack["events_df"].to_csv(f"{tf_prefix}_events.csv", index=False)

        if strategy_cfg.get("feature_toggles", {}).get("save_charts", True):
            renderer.render_timeframe_package(
                timeframe=tf,
                candles_df=result_pack["candles_df"],
                swings_df=result_pack["swings_df"],
                fvg_df=result_pack["fvg_df"],
                events_df=result_pack["events_df"],
                trades_df=result_pack["trades_df"],
                equity_curve=result_pack["equity_curve"],
            )

    report_paths = reporter.generate(all_results)

    console.print("\n[bold cyan]Backtest tamamlandı.[/bold cyan]")
    console.print("Üretilen dosyalar:")
    for key, path in report_paths.items():
        console.print(f"- {key}: {path}")


if __name__ == "__main__":
    main()
