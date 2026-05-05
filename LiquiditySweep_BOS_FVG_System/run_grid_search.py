from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from rich.console import Console

from core.data_manager import DataManager
from core.grid_search import GridSearchOptimizer
from core.logger import setup_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HTF filtresiz parametre tarama (grid search) ve optimize konfig ile backtest"
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=str(Path(__file__).resolve().parent),
        help="Proje kök klasörü",
    )
    parser.add_argument(
        "--strategy-config",
        type=str,
        default="config/strategy_config.json",
        help="Temel strateji konfigürasyon dosyası",
    )
    parser.add_argument(
        "--rr-values",
        type=str,
        default="1.5,2.0,2.5,3.0",
        help="RR adayları, virgülle ayrılmış",
    )
    parser.add_argument(
        "--pivot-values",
        type=str,
        default="2,3,4",
        help="Pivot sensitivity adayları, virgülle ayrılmış",
    )
    parser.add_argument(
        "--fvg-values",
        type=str,
        default="6,8,10,12",
        help="Minimum FVG boyutu adayları (point), virgülle ayrılmış",
    )
    return parser.parse_args()


def parse_float_list(payload: str) -> list[float]:
    return [float(x.strip()) for x in payload.split(",") if x.strip()]


def parse_int_list(payload: str) -> list[int]:
    return [int(x.strip()) for x in payload.split(",") if x.strip()]


def main() -> None:
    args = parse_args()
    project_root = Path(args.project_root).resolve()

    logger = setup_logger(project_root / "logs")
    console = Console()
    dm = DataManager(project_root, logger)

    system_cfg = dm.load_json_config(project_root / "config" / "system_config.json")
    base_strategy_cfg = dm.load_json_config(project_root / args.strategy_config)

    symbol = system_cfg["symbol"]
    timeframes = system_cfg["timeframes"]

    data_by_tf = {tf: dm.load_raw_data(symbol, tf) for tf in timeframes}
    h1_df = dm.load_raw_data(symbol, "H1")

    rr_values = parse_float_list(args.rr_values)
    pivot_values = parse_int_list(args.pivot_values)
    fvg_values = parse_int_list(args.fvg_values)

    optimizer = GridSearchOptimizer(
        project_root=project_root,
        system_cfg=system_cfg,
        base_strategy_cfg=base_strategy_cfg,
        logger=logger,
    )

    results_df, optimized_cfg = optimizer.run(
        rr_values=rr_values,
        pivot_values=pivot_values,
        fvg_values=fvg_values,
        symbol=symbol,
        timeframes=timeframes,
        data_by_tf=data_by_tf,
        h1_df=h1_df,
    )

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    grid_csv = project_root / "results" / f"grid_search_results_{ts}.csv"
    optimized_cfg_path = project_root / "config" / "strategy_config_optimized_no_htf.json"

    optimizer.save_outputs(
        results_df=results_df,
        optimized_cfg=optimized_cfg,
        csv_path=grid_csv,
        json_path=optimized_cfg_path,
    )

    console.print("[bold green]Grid search tamamlandı.[/bold green]")
    console.print(f"Sonuçlar: {grid_csv}")
    console.print(f"Optimize konfig: {optimized_cfg_path}")


if __name__ == "__main__":
    main()
