"""
Paper/Live Trading Başlatıcı
==============================
Kullanım:
    python run_paper_trader.py                          # Varsayılan: M15, kuru çalıştırma
    python run_paper_trader.py --timeframes M15 H1      # Birden fazla TF
    python run_paper_trader.py --live                   # Gerçek emir gönder (dikkatli!)
    python run_paper_trader.py --strategy-config config/strategy_config_optimized_no_htf.json

Önemli:
    - Varsayılan olarak DRY_RUN=True → emir GÖNDERİLMEZ, sadece loglanır.
    - Gerçek emir için --live bayrağını ekleyin.
    - Hibrit modda M15 otomatik olarak OrderBlock stratejisine yönlenir.
    - H1 ve H4, Liquidity Sweep BOS FVG stratejisiyle çalışır.
    - Her TF kendi magic numarasıyla MT5'te BAĞIMSIZ işlem açar.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Proje kökü sys.path'e eklenir.
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.paper_trader import PaperTrader


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("PaperTrader")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)

    # Dosyaya da yaz (tüm detaylar).
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(log_dir / "paper_trader.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
    logger.addHandler(fh)

    # Strateji içindeki debug logları (FVG, sweep, BOS) terminale basılmasın.
    # Sadece dosyaya gider.
    strategy_logger = logging.getLogger("liquidity_sweep")
    strategy_logger.setLevel(logging.WARNING)

    return logger


def main() -> None:
    parser = argparse.ArgumentParser(description="SMC Paper/Live Trading")
    parser.add_argument(
        "--timeframes", nargs="+", default=["M15"],
        help="Aktif timeframe(ler). Örn: M15 H1"
    )
    parser.add_argument(
        "--strategy-config", default="config/strategy_config_optimized_no_htf.json",
        help="Strateji konfigürasyonu dosyası"
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Gerçek emir gönder (varsayılan: kuru çalıştırma)"
    )
    parser.add_argument(
        "--max-signals", type=int, default=0,
        help="Bu kadar sinyal sonrası otomatik durdur (0 = sınırsız)"
    )
    args = parser.parse_args()

    logger = setup_logger()

    system_config_path = PROJECT_ROOT / "config" / "system_config.json"
    strategy_config_path = PROJECT_ROOT / args.strategy_config

    with open(system_config_path, "r", encoding="utf-8") as f:
        system_cfg = json.load(f)
    with open(strategy_config_path, "r", encoding="utf-8") as f:
        strategy_cfg = json.load(f)

    dry_run = not args.live
    if dry_run:
        logger.info("=" * 60)
        logger.info("KURU ÇALIŞTIRMA MODU – emir GÖNDERİLMEZ")
        logger.info("Gerçek emir için: python run_paper_trader.py --live")
        logger.info("=" * 60)
    else:
        logger.warning("CANLI MOD AKTİF – gerçek emirler gönderilecek!")

    trader = PaperTrader(
        project_root=PROJECT_ROOT,
        system_cfg=system_cfg,
        strategy_cfg=strategy_cfg,
        active_timeframes=args.timeframes,
        logger=logger,
        dry_run=dry_run,
    )
    trader.max_signals = args.max_signals

    if not trader.connect():
        logger.error("MT5 bağlantısı kurulamadı. Çıkılıyor.")
        sys.exit(1)

    trader.run_forever()


if __name__ == "__main__":
    main()
