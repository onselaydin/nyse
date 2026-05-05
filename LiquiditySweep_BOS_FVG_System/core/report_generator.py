from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.models import BacktestResult


class ReportGenerator:
    """CSV/Excel/HTML rapor çıktıları üretir."""

    def __init__(self, project_root: Path, logger):
        self.project_root = project_root
        self.logger = logger

    def generate(
        self,
        all_results: list[dict[str, Any]],
    ) -> dict[str, Path]:
        reports_dir = self.project_root / "reports"
        results_dir = self.project_root / "results"
        reports_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        trades_frames = []
        summary_rows = []
        equity_rows = []

        for item in all_results:
            tf = item["timeframe"]
            result: BacktestResult = item["result"]
            trades_df = item["trades_df"].copy()
            if not trades_df.empty:
                trades_df["timeframe"] = tf
                trades_frames.append(trades_df)

            row = asdict(result)
            row.pop("equity_curve", None)
            summary_rows.append(row)

            for idx, eq in enumerate(result.equity_curve):
                equity_rows.append({"timeframe": tf, "bar_index": idx, "equity": eq})

        summary_df = pd.DataFrame(summary_rows)
        trades_df = pd.concat(trades_frames, ignore_index=True) if trades_frames else pd.DataFrame()
        equity_df = pd.DataFrame(equity_rows)

        csv_summary = results_dir / f"summary_{timestamp}.csv"
        csv_trades = results_dir / f"trades_{timestamp}.csv"
        csv_equity = results_dir / f"equity_{timestamp}.csv"

        summary_df.to_csv(csv_summary, index=False)
        trades_df.to_csv(csv_trades, index=False)
        equity_df.to_csv(csv_equity, index=False)

        xlsx_path = reports_dir / f"rapor_{timestamp}.xlsx"
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="Ozet", index=False)
            trades_df.to_excel(writer, sheet_name="Islemler", index=False)
            equity_df.to_excel(writer, sheet_name="Equity", index=False)

        html_path = reports_dir / f"ozet_{timestamp}.html"
        html_content = self._build_html_summary(summary_df, trades_df)
        html_path.write_text(html_content, encoding="utf-8")

        self.logger.info("Raporlar üretildi: %s", reports_dir)
        return {
            "summary_csv": csv_summary,
            "trades_csv": csv_trades,
            "equity_csv": csv_equity,
            "excel": xlsx_path,
            "html": html_path,
        }

    def _build_html_summary(self, summary_df: pd.DataFrame, trades_df: pd.DataFrame) -> str:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        total_trades = int(summary_df["total_trades"].sum()) if not summary_df.empty else 0
        total_pnl = float(summary_df["total_pnl"].sum()) if not summary_df.empty else 0.0
        avg_win_rate = float(summary_df["win_rate"].mean()) if not summary_df.empty else 0.0
        avg_pf = float(summary_df["profit_factor"].replace(float("inf"), pd.NA).dropna().mean()) if not summary_df.empty else 0.0

        summary_table = summary_df.to_html(index=False, classes="table") if not summary_df.empty else "<p>Özet veri yok.</p>"
        trades_table = trades_df.head(100).to_html(index=False, classes="table") if not trades_df.empty else "<p>İşlem verisi yok.</p>"

        return f"""
<!DOCTYPE html>
<html lang=\"tr\">
<head>
  <meta charset=\"UTF-8\" />
  <title>Liquidity Sweep BOS FVG - Backtest Özeti</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background:#f4f7fb; color:#102a43; margin: 24px; }}
    .card {{ background:white; border-radius:12px; padding:16px 20px; box-shadow: 0 6px 16px rgba(16,42,67,0.08); margin-bottom:16px; }}
    .grid {{ display:grid; grid-template-columns: repeat(4, minmax(120px,1fr)); gap:12px; }}
    .kpi {{ background:#e6eef7; border-radius:10px; padding:12px; }}
    .kpi b {{ display:block; font-size:20px; }}
    .table {{ border-collapse: collapse; width:100%; font-size:14px; }}
    .table th,.table td {{ border:1px solid #d9e2ec; padding:8px; text-align:left; }}
    .table th {{ background:#bcccdc; }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>Liquidity Sweep + BOS + FVG Backtest Özeti</h1>
    <p>Üretim zamanı: {now}</p>
    <p>Bu rapor yönlü (bullish + bearish) kurulumlar için üretilmiştir.</p>
  </div>

  <div class=\"card grid\">
    <div class=\"kpi\"><span>Toplam İşlem</span><b>{total_trades}</b></div>
    <div class=\"kpi\"><span>Toplam PnL (USD)</span><b>{total_pnl:.2f}</b></div>
    <div class=\"kpi\"><span>Ortalama Win Rate</span><b>{avg_win_rate:.2f}%</b></div>
    <div class=\"kpi\"><span>Ortalama Profit Factor</span><b>{avg_pf:.2f}</b></div>
  </div>

  <div class=\"card\">
    <h2>Timeframe Bazlı Özet</h2>
    {summary_table}
  </div>

  <div class=\"card\">
    <h2>İlk 100 İşlem</h2>
    {trades_table}
  </div>
</body>
</html>
"""
