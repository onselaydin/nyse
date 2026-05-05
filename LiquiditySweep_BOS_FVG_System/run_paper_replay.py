"""
Paper Trading Replay Modu
==========================
Mevcut backtest verilerini (CSV) canlı fiyat akışı gibi simüle eder.
Her bar tek tek işlenir; sinyal üretildiğinde emir log satırı basılır.

Kullanım:
    python run_paper_replay.py                          # M15, ilk 10 sinyal
    python run_paper_replay.py --timeframes M15 H1 H4  # Birden fazla TF
    python run_paper_replay.py --max-signals 10        # 10 sinyal sonrası dur

Bu mod gerçek emir göndermez — sistemi canlı ortamdan önce test etmek içindir.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategies.liquidity_sweep_bos_fvg import LiquiditySweepBOSFVGStrategy


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("PaperReplay")
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(h)
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(log_dir / "paper_replay.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
    logger.addHandler(fh)
    return logger


def build_h1_context(h1_df: pd.DataFrame, up_to_index: int) -> dict:
    """h1_df'nin up_to_index'e kadar olan kısmından H1 bağlamı üretir."""
    window = h1_df.iloc[:up_to_index + 1]
    if len(window) < 52:
        return {"structure_bullish": False, "structure_bearish": False,
                "price_above_ema50": False, "price_below_ema50": False}
    closes = window["Close"].tolist()
    k = 2.0 / 51
    ema = sum(closes[:50]) / 50
    for c in closes[50:]:
        ema = c * k + ema * (1 - k)
    last = closes[-1]
    prev = closes[-2]
    prev2 = closes[-3]
    return {
        "structure_bullish": last > prev > prev2,
        "structure_bearish": last < prev < prev2,
        "price_above_ema50": last > ema,
        "price_below_ema50": last < ema,
    }


def replay_timeframe(
    tf: str,
    df: pd.DataFrame,
    h1_df: pd.DataFrame,
    strategy_cfg: dict,
    max_signals: int,
    logger: logging.Logger,
) -> list[dict]:
    """
    Belirtilen TF'nin tüm barlarını sırayla işler.
    Her bar 'şu an canlı son bar' gibi değerlendirilir.
    Sinyal üretildiğinde loglanır ve listeye eklenir.
    """
    silent = logging.getLogger("replay.silent")
    silent.setLevel(logging.CRITICAL)

    strategy = LiquiditySweepBOSFVGStrategy(strategy_cfg, silent)
    signals_found: list[dict] = []
    last_signal_time = None

    # En az 50 bar warmup sonrası sinyal arayışına gir.
    for i in range(len(df)):
        h1_ctx = build_h1_context(h1_df, min(i, len(h1_df) - 1))
        result = strategy.process_bar(df, i, h1_ctx)

        if result is None:
            continue
        if result["time"] == last_signal_time:
            continue

        last_signal_time = result["time"]
        result["timeframe"] = tf
        signals_found.append(result)

        side = result.get("side", "?").upper()
        entry = result["entry_price"]
        sl = result["stop_loss"]
        tp = result["take_profit"]
        sl_pips = abs(entry - sl) * 10000
        tp_pips = abs(tp - entry) * 10000
        rr = tp_pips / sl_pips if sl_pips > 0 else 0

        logger.info("─" * 68)
        logger.info(
            "SİNYAL #%-3d | %-4s %-3s | %s",
            len(signals_found), tf, side, result["time"].strftime("%Y-%m-%d %H:%M")
        )
        logger.info(
            "  Giriş : %.5f  |  SL: %.5f (%+.1f pip)  |  TP: %.5f (%+.1f pip)  |  RR: %.1f",
            entry, sl, -sl_pips if side == "BUY" else sl_pips,
            tp, tp_pips, rr
        )
        logger.info("  Sebep : %s", result.get("reason", ""))
        logger.info("─" * 68)

        if max_signals > 0 and len(signals_found) >= max_signals:
            break

    return signals_found


def main() -> None:
    parser = argparse.ArgumentParser(description="SMC Paper Replay")
    parser.add_argument("--timeframes", nargs="+", default=["M15", "H1", "H4"])
    parser.add_argument("--strategy-config", default="config/strategy_config_optimized_no_htf.json")
    parser.add_argument("--max-signals", type=int, default=10)
    args = parser.parse_args()

    logger = setup_logger()

    with open(PROJECT_ROOT / "config" / "system_config.json", encoding="utf-8") as f:
        system_cfg = json.load(f)
    with open(PROJECT_ROOT / args.strategy_config, encoding="utf-8") as f:
        strategy_cfg = json.load(f)

    data_dir = PROJECT_ROOT / system_cfg["paths"]["data_dir"]
    symbol = system_cfg["symbol"]

    # H1 verisi tüm TF'ler için HTF bağlamı olarak kullanılır.
    h1_path = data_dir / f"{symbol}_H1.csv"
    if not h1_path.exists():
        logger.error("H1 verisi bulunamadı: %s", h1_path)
        sys.exit(1)
    h1_df = pd.read_csv(h1_path, parse_dates=["time"])

    logger.info("=" * 68)
    logger.info("PAPER REPLAY MODU — Gerçek emir GÖNDERİLMEZ")
    logger.info("TF'ler: %s | Max sinyal: %d", args.timeframes, args.max_signals)
    logger.info("=" * 68)

    all_signals: list[dict] = []

    for tf in args.timeframes:
        csv_path = data_dir / f"{symbol}_{tf}.csv"
        if not csv_path.exists():
            logger.warning("%s verisi bulunamadı: %s — atlanıyor.", tf, csv_path)
            continue

        df = pd.read_csv(csv_path, parse_dates=["time"])
        logger.info("\n>>> %s — %d bar taranıyor...", tf, len(df))

        remaining = args.max_signals - len(all_signals)
        if remaining <= 0:
            break

        signals = replay_timeframe(tf, df, h1_df, strategy_cfg, remaining, logger)
        all_signals.extend(signals)

        logger.info(">>> %s tamamlandı: %d sinyal bulundu.", tf, len(signals))

    # Özet tablo
    logger.info("\n%s", "=" * 68)
    logger.info("ÖZET — Toplam %d sinyal", len(all_signals))
    logger.info("%-5s %-4s %-6s %-10s %-10s %-10s %-6s", "#", "TF", "Yön", "Giriş", "SL", "TP", "RR")
    logger.info("─" * 68)
    for idx, sig in enumerate(all_signals, 1):
        side = sig.get("side", "?").upper()
        e = sig["entry_price"]
        sl = sig["stop_loss"]
        tp = sig["take_profit"]
        sl_p = abs(e - sl) * 10000
        tp_p = abs(tp - e) * 10000
        rr = tp_p / sl_p if sl_p > 0 else 0
        logger.info(
            "%-5d %-4s %-6s %-10.5f %-10.5f %-10.5f %-6.1f",
            idx, sig["timeframe"], side, e, sl, tp, rr,
        )
    logger.info("=" * 68)


if __name__ == "__main__":
    main()
