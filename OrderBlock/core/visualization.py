from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def plot_equity_matplotlib(equity_curve: Sequence[float], out_path: Path, title: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(11, 5))
    plt.plot(equity_curve, linewidth=1.4)
    plt.title(title)
    plt.xlabel("Bar")
    plt.ylabel("Bakiye (USD)")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def plot_equity_plotly(equity_curve: Sequence[float], out_path: Path, title: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=list(equity_curve), mode="lines", name="Equity"))
    fig.update_layout(title=title, xaxis_title="Bar", yaxis_title="Bakiye (USD)", template="plotly_white")
    fig.write_html(str(out_path), include_plotlyjs="cdn")


def plot_price_structure(
    candles_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    out_path: Path,
    title: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig = make_subplots(rows=1, cols=1, shared_xaxes=True)

    fig.add_trace(
        go.Candlestick(
            x=candles_df["time"],
            open=candles_df["Open"],
            high=candles_df["High"],
            low=candles_df["Low"],
            close=candles_df["Close"],
            name="EURUSD",
        )
    )

    if not trades_df.empty:
        buys = trades_df[trades_df["side"] == "buy"]
        sells = trades_df[trades_df["side"] == "sell"]

        fig.add_trace(
            go.Scatter(
                x=buys["entry_time"],
                y=buys["entry_price"],
                mode="markers",
                marker=dict(color="green", size=8, symbol="triangle-up"),
                name="BUY Entry",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=sells["entry_time"],
                y=sells["entry_price"],
                mode="markers",
                marker=dict(color="red", size=8, symbol="triangle-down"),
                name="SELL Entry",
            )
        )

    fig.update_layout(
        title=title,
        template="plotly_white",
        xaxis_title="Zaman",
        yaxis_title="Fiyat",
        xaxis_rangeslider_visible=False,
    )
    fig.write_html(str(out_path), include_plotlyjs="cdn")
