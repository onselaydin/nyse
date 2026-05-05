from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from tqdm import tqdm

from core.indicators import ema
from core.models import BacktestResult
from core.trade_manager import TradeManager
from strategies.liquidity_sweep_bos_fvg import LiquiditySweepBOSFVGStrategy


class Backtester:
    """Sıralı mum işleme ile look-ahead bias'sız backtest motoru."""

    def __init__(self, project_root: Path, system_cfg: dict[str, Any], strategy_cfg: dict[str, Any], logger):
        self.project_root = project_root
        self.system_cfg = system_cfg
        self.strategy_cfg = strategy_cfg
        self.logger = logger

    def _prepare_h1_context(self, h1_df: pd.DataFrame) -> pd.DataFrame:
        """H1 trend filtresi için EMA50 ve yönlü yapı işaretleri üretir."""

        h1 = h1_df.copy().sort_values("time").reset_index(drop=True)
        ema_period = int(self.strategy_cfg.get("htf_filter", {}).get("ema_period", 50))
        h1["ema50"] = ema(h1["Close"], ema_period)

        # Basit structure filtresi: ardışık kapanışlarla yön momentumu ölçülür.
        h1["structure_bullish"] = (
            (h1["Close"] > h1["Close"].shift(1)) & (h1["Close"].shift(1) > h1["Close"].shift(2))
        )
        h1["structure_bearish"] = (
            (h1["Close"] < h1["Close"].shift(1)) & (h1["Close"].shift(1) < h1["Close"].shift(2))
        )
        h1["price_above_ema50"] = h1["Close"] > h1["ema50"]
        h1["price_below_ema50"] = h1["Close"] < h1["ema50"]

        return h1[
            [
                "time",
                "structure_bullish",
                "structure_bearish",
                "price_above_ema50",
                "price_below_ema50",
                "ema50",
            ]
        ]

    def _attach_h1_context(self, df: pd.DataFrame, h1_context_df: pd.DataFrame) -> pd.DataFrame:
        """Her muma kendisinden önceki/aynı H1 bar bağlanır (geri dönük eşleşme)."""

        base = df.copy().sort_values("time").reset_index(drop=True)
        htf = h1_context_df.copy().sort_values("time").reset_index(drop=True)

        merged = pd.merge_asof(
            base,
            htf,
            on="time",
            direction="backward",
        )
        merged["structure_bullish"] = merged["structure_bullish"].fillna(False)
        merged["structure_bearish"] = merged["structure_bearish"].fillna(False)
        merged["price_above_ema50"] = merged["price_above_ema50"].fillna(False)
        merged["price_below_ema50"] = merged["price_below_ema50"].fillna(False)
        return merged

    def run(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        h1_df: pd.DataFrame,
    ) -> dict[str, Any]:
        """Tek timeframe için backtest çalıştırır."""

        self.logger.info("Backtest başlatıldı | %s %s", symbol, timeframe)

        strategy = LiquiditySweepBOSFVGStrategy(self.strategy_cfg, self.logger)
        fixed_lot = float(self.system_cfg["account"]["fixed_lot"])

        # Broker maliyet parametreleri system_config'den alınır.
        costs = self.system_cfg.get("broker_costs", {})
        tm = TradeManager(
            symbol=symbol,
            timeframe=timeframe,
            fixed_lot=fixed_lot,
            commission_per_lot_usd=float(costs.get("commission_per_lot_usd", 0.0)),
            swap_long_pips_per_night=float(costs.get("swap_long_pips_per_night", 0.0)),
            swap_short_pips_per_night=float(costs.get("swap_short_pips_per_night", 0.0)),
            apply_commission=bool(costs.get("apply_commission", True)),
            apply_swap=bool(costs.get("apply_swap", True)),
        )

        h1_ctx_df = self._prepare_h1_context(h1_df)
        work_df = self._attach_h1_context(df, h1_ctx_df)

        initial_balance = float(self.system_cfg["account"]["initial_balance"])
        balance = initial_balance
        equity_curve = []

        exec_cfg = self.system_cfg.get("execution", {})
        default_spread = float(exec_cfg.get("default_spread_points", 8))
        max_open_positions = int(exec_cfg.get("max_open_positions", 3))

        for i in tqdm(range(len(work_df)), desc=f"Backtest {timeframe}"):
            candle = work_df.iloc[i]

            closed_now = tm.update_open_trades(
                index=i,
                time=pd.Timestamp(candle["time"]).to_pydatetime(),
                high=float(candle["High"]),
                low=float(candle["Low"]),
            )
            if closed_now:
                balance += sum(t.pnl_usd for t in closed_now)

            htf_context = {
                "structure_bullish": bool(candle["structure_bullish"]),
                "structure_bearish": bool(candle["structure_bearish"]),
                "price_above_ema50": bool(candle["price_above_ema50"]),
                "price_below_ema50": bool(candle["price_below_ema50"]),
            }

            signal = strategy.process_bar(work_df, i, htf_context)
            if signal and tm.can_open_trade(max_open_positions):
                spread_points = (
                    float(candle["spread"])
                    if "spread" in work_df.columns and not np.isnan(candle.get("spread", np.nan))
                    else default_spread
                )
                if signal.get("side") == "sell":
                    tm.open_sell_trade(
                        index=i,
                        time=signal["time"],
                        entry_price=float(signal["entry_price"]),
                        stop_loss=float(signal["stop_loss"]),
                        take_profit=float(signal["take_profit"]),
                        spread_points=float(spread_points),
                        reason=signal["reason"],
                    )
                else:
                    tm.open_buy_trade(
                        index=i,
                        time=signal["time"],
                        entry_price=float(signal["entry_price"]),
                        stop_loss=float(signal["stop_loss"]),
                        take_profit=float(signal["take_profit"]),
                        spread_points=float(spread_points),
                        reason=signal["reason"],
                    )

            floating_pnl = 0.0
            for ot in tm.open_trades:
                current_price = float(candle["Close"])
                if ot.side == "sell":
                    floating_pips = (ot.entry_price - current_price) * 10000
                else:
                    floating_pips = (current_price - ot.entry_price) * 10000
                floating_pnl += floating_pips * (TradeManager.PIP_VALUE_PER_LOT_EURUSD * ot.lot_size)
            equity_curve.append(balance + floating_pnl)

        if tm.open_trades:
            last = work_df.iloc[-1]
            closed_end = tm.force_close_all(
                index=len(work_df) - 1,
                time=pd.Timestamp(last["time"]).to_pydatetime(),
                close_price=float(last["Close"]),
            )
            balance += sum(t.pnl_usd for t in closed_end)

        closed_df = tm.trades_to_dataframe(tm.closed_trades)
        metrics = self._compute_metrics(initial_balance, balance, closed_df, equity_curve, timeframe)

        return {
            "timeframe": timeframe,
            "trades_df": closed_df,
            "swings_df": strategy.export_swings(),
            "fvg_df": strategy.export_fvg(),
            "events_df": strategy.export_debug_events(),
            "equity_curve": equity_curve,
            "result": metrics,
            "candles_df": work_df,
        }

    def _compute_metrics(
        self,
        initial_balance: float,
        final_balance: float,
        trades_df: pd.DataFrame,
        equity_curve: list[float],
        timeframe: str,
    ) -> BacktestResult:
        if trades_df.empty:
            return BacktestResult(
                timeframe=timeframe,
                initial_balance=initial_balance,
                final_balance=final_balance,
                total_pnl=final_balance - initial_balance,
                win_rate=0.0,
                profit_factor=0.0,
                max_drawdown_pct=0.0,
                total_trades=0,
                wins=0,
                losses=0,
                rr_avg=0.0,
                equity_curve=equity_curve,
            )

        wins = int((trades_df["pnl_usd"] > 0).sum())
        losses = int((trades_df["pnl_usd"] <= 0).sum())
        total = int(len(trades_df))
        win_rate = (wins / total) * 100 if total else 0.0

        gross_profit = trades_df.loc[trades_df["pnl_usd"] > 0, "pnl_usd"].sum()
        gross_loss = abs(trades_df.loc[trades_df["pnl_usd"] <= 0, "pnl_usd"].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        eq = pd.Series(equity_curve if equity_curve else [initial_balance])
        rolling_max = eq.cummax()
        dd = (eq - rolling_max) / rolling_max * 100
        max_dd = abs(float(dd.min())) if not dd.empty else 0.0

        rr_avg = float(trades_df["rr_realized"].mean()) if "rr_realized" in trades_df.columns else 0.0

        return BacktestResult(
            timeframe=timeframe,
            initial_balance=initial_balance,
            final_balance=final_balance,
            total_pnl=final_balance - initial_balance,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown_pct=max_dd,
            total_trades=total,
            wins=wins,
            losses=losses,
            rr_avg=rr_avg,
            equity_curve=equity_curve,
        )
