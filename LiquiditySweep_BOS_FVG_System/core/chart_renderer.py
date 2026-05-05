from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import plotly.graph_objects as go


class ChartRenderer:
    """İşlem ve yapı sinyallerini görselleştirir."""

    def __init__(self, project_root: Path, logger):
        self.project_root = project_root
        self.logger = logger

    def render_timeframe_package(
        self,
        timeframe: str,
        candles_df: pd.DataFrame,
        swings_df: pd.DataFrame,
        fvg_df: pd.DataFrame,
        events_df: pd.DataFrame,
        trades_df: pd.DataFrame,
        equity_curve: list[float],
    ) -> dict[str, Path]:
        charts_dir = self.project_root / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)

        price_chart = charts_dir / f"{timeframe}_price_structure.png"
        equity_chart = charts_dir / f"{timeframe}_equity_curve.png"
        equity_html = charts_dir / f"{timeframe}_equity_curve.html"

        self._plot_price_chart(price_chart, candles_df, swings_df, fvg_df, events_df, trades_df, timeframe)
        self._plot_equity_matplotlib(equity_chart, equity_curve, timeframe)
        self._plot_equity_plotly(equity_html, equity_curve, timeframe)

        self.logger.info("Grafikler kaydedildi | TF=%s", timeframe)
        return {
            "price_chart": price_chart,
            "equity_chart": equity_chart,
            "equity_html": equity_html,
        }

    def _plot_price_chart(
        self,
        output_path: Path,
        candles_df: pd.DataFrame,
        swings_df: pd.DataFrame,
        fvg_df: pd.DataFrame,
        events_df: pd.DataFrame,
        trades_df: pd.DataFrame,
        timeframe: str,
    ) -> None:
        df = candles_df.copy()
        df = df.tail(400).copy()
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")

        addplots = []

        if not swings_df.empty:
            local_swings = swings_df.copy()
            local_swings["time"] = pd.to_datetime(local_swings["time"], utc=True)
            local_swings = local_swings[local_swings["time"].isin(df.index)]

            lows = local_swings[local_swings["kind"] == "low"]
            highs = local_swings[local_swings["kind"] == "high"]

            if not lows.empty:
                low_series = pd.Series(index=df.index, dtype=float)
                low_series.loc[lows["time"]] = lows["price"].values
                addplots.append(mpf.make_addplot(low_series, type="scatter", markersize=30, marker="^", color="green"))

            if not highs.empty:
                high_series = pd.Series(index=df.index, dtype=float)
                high_series.loc[highs["time"]] = highs["price"].values
                addplots.append(mpf.make_addplot(high_series, type="scatter", markersize=30, marker="v", color="red"))

        if not trades_df.empty:
            local_trades = trades_df.copy()
            local_trades["open_time"] = pd.to_datetime(local_trades["open_time"], utc=True)
            local_trades = local_trades[local_trades["open_time"].isin(df.index)]
            if not local_trades.empty:
                long_trades = local_trades[local_trades["side"] == "buy"]
                short_trades = local_trades[local_trades["side"] == "sell"]

                if not long_trades.empty:
                    long_entry_series = pd.Series(index=df.index, dtype=float)
                    long_entry_series.loc[long_trades["open_time"]] = long_trades["entry_price"].values
                    addplots.append(
                        mpf.make_addplot(
                            long_entry_series,
                            type="scatter",
                            marker="^",
                            markersize=90,
                            color="dodgerblue",
                        )
                    )

                if not short_trades.empty:
                    short_entry_series = pd.Series(index=df.index, dtype=float)
                    short_entry_series.loc[short_trades["open_time"]] = short_trades["entry_price"].values
                    addplots.append(
                        mpf.make_addplot(
                            short_entry_series,
                            type="scatter",
                            marker="v",
                            markersize=90,
                            color="purple",
                        )
                    )

        style = mpf.make_mpf_style(base_mpf_style="yahoo", gridstyle="--")
        fig, axes = mpf.plot(
            df[["Open", "High", "Low", "Close", "Volume"]],
            type="candle",
            style=style,
            addplot=addplots if addplots else None,
            volume=True,
            returnfig=True,
            figsize=(16, 9),
            title=f"{timeframe} - SMC Yapı Grafiği (Son 400 Mum)",
        )

        ax = axes[0]

        if not fvg_df.empty:
            local_fvg = fvg_df.copy()
            local_fvg["created_time"] = pd.to_datetime(local_fvg["created_time"], utc=True)
            local_fvg = local_fvg[local_fvg["created_time"] >= df.index.min()]
            for _, z in local_fvg.tail(20).iterrows():
                start = z["created_time"]
                end = df.index.max()
                ax.fill_between([start, end], z["lower"], z["upper"], color="orange", alpha=0.08)

        if not events_df.empty:
            local_events = events_df.copy()
            local_events["time"] = pd.to_datetime(local_events["time"], utc=True)
            local_events = local_events[local_events["time"].isin(df.index)]
            bos = local_events[local_events["event"].isin(["bos_bullish", "bos_bearish"])]
            sweep = local_events[
                local_events["event"].isin(["liquidity_sweep_bullish", "liquidity_sweep_bearish"])
            ]

            for _, row in bos.iterrows():
                ax.annotate("BOS", (row["time"], row["price"]), color="navy", fontsize=8)
            for _, row in sweep.iterrows():
                ax.annotate("Sweep", (row["time"], row["price"]), color="darkgreen", fontsize=8)

        fig.savefig(output_path, dpi=180, bbox_inches="tight")
        plt.close(fig)

    def _plot_equity_matplotlib(self, output_path: Path, equity_curve: list[float], timeframe: str) -> None:
        plt.figure(figsize=(12, 4))
        plt.plot(equity_curve, color="#0f4c81", linewidth=1.8)
        plt.title(f"{timeframe} Equity Curve")
        plt.xlabel("Bar")
        plt.ylabel("Equity (USD)")
        plt.grid(alpha=0.25)
        plt.tight_layout()
        plt.savefig(output_path, dpi=180)
        plt.close()

    def _plot_equity_plotly(self, output_path: Path, equity_curve: list[float], timeframe: str) -> None:
        fig = go.Figure()
        fig.add_trace(go.Scatter(y=equity_curve, mode="lines", name="Equity"))
        fig.update_layout(
            title=f"{timeframe} Equity Curve (İnteraktif)",
            xaxis_title="Bar",
            yaxis_title="Equity (USD)",
            template="plotly_white",
        )
        fig.write_html(str(output_path), include_plotlyjs="cdn")
