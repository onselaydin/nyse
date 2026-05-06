from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

from config import AppConfig
from core.models import BacktestMetrics, Trade
from strategy.orderblock_strategy import OrderBlockStrategy, TradeSignal


class Backtester:
    PIP_VALUE_PER_LOT_EURUSD = 10.0
    PIPS_PER_PRICE_UNIT = 10000.0

    def __init__(self, cfg: AppConfig, logger):
        self.cfg = cfg
        self.logger = logger

    def _compute_h1_context(self, h1_df: pd.DataFrame) -> pd.DataFrame:
        df = h1_df.copy().sort_values("time").reset_index(drop=True)
        ema_period = 50
        df["ema50"] = df["Close"].ewm(span=ema_period, adjust=False).mean()
        df["structure_bullish"] = (df["Close"] > df["Close"].shift(1)) & (df["Close"].shift(1) > df["Close"].shift(2))
        df["structure_bearish"] = (df["Close"] < df["Close"].shift(1)) & (df["Close"].shift(1) < df["Close"].shift(2))
        return df[["time", "ema50", "structure_bullish", "structure_bearish"]]

    def _compute_h4_context(self, h4_df: pd.DataFrame) -> pd.DataFrame:
        df = h4_df.copy().sort_values("time").reset_index(drop=True)
        df["ema50"] = df["Close"].ewm(span=50, adjust=False).mean()
        df["trend_bullish"] = (df["Close"] > df["ema50"]) & (df["ema50"] > df["ema50"].shift(1))
        df["trend_bearish"] = (df["Close"] < df["ema50"]) & (df["ema50"] < df["ema50"].shift(1))
        return df[["time", "trend_bullish", "trend_bearish"]]

    def _attach_context(
        self,
        exec_df: pd.DataFrame,
        h1_ctx: pd.DataFrame,
        h4_ctx: pd.DataFrame,
    ) -> pd.DataFrame:
        base = exec_df.sort_values("time").reset_index(drop=True).copy()

        merged = pd.merge_asof(
            base,
            h1_ctx.sort_values("time"),
            on="time",
            direction="backward",
        )
        merged = pd.merge_asof(
            merged.sort_values("time"),
            h4_ctx.sort_values("time"),
            on="time",
            direction="backward",
        )

        for col in ["structure_bullish", "structure_bearish", "trend_bullish", "trend_bearish"]:
            merged[col] = merged[col].fillna(False)

        return merged

    def _classify_session(self, ts: pd.Timestamp) -> str:
        ts_utc = pd.Timestamp(ts).tz_convert("UTC") if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).tz_localize("UTC")
        hour = ts_utc.hour

        london = self.cfg.session.london
        ny = self.cfg.session.new_york

        if london.start_hour_utc <= hour <= london.end_hour_utc:
            return "london"
        if ny.start_hour_utc <= hour <= ny.end_hour_utc:
            return "new_york"
        return "out_of_session"

    def _pnl_usd(self, side: str, entry: float, exit_price: float, lot: float) -> float:
        if side == "buy":
            pips = (exit_price - entry) * self.PIPS_PER_PRICE_UNIT
        else:
            pips = (entry - exit_price) * self.PIPS_PER_PRICE_UNIT
        return float(pips * (self.PIP_VALUE_PER_LOT_EURUSD * lot))

    def _close_trade(
        self,
        trade: Trade,
        exit_price: float,
        exit_time: datetime,
        exit_index: int,
        result: str,
        balance_before: float,
    ) -> Trade:
        pnl = self._pnl_usd(trade.side, trade.entry_price, exit_price, trade.lot_size)
        risk = abs(trade.entry_price - trade.stop_loss)
        rr_realized = 0.0 if risk <= 0 else abs((exit_price - trade.entry_price) / risk)

        trade.exit_price = float(exit_price)
        trade.exit_time = exit_time
        trade.exit_index = exit_index
        trade.result = result
        trade.pnl_usd = float(pnl)
        trade.pnl_pct = float((pnl / balance_before) * 100 if balance_before > 0 else 0.0)
        trade.rr_realized = float(rr_realized)
        return trade

    def run_single_timeframe(
        self,
        timeframe: str,
        exec_df: pd.DataFrame,
        h1_df: pd.DataFrame,
        h4_df: pd.DataFrame,
        ai_inference: Optional[Any] = None,
    ) -> dict[str, Any]:
        strategy = OrderBlockStrategy(self.cfg, self.logger)
        lot = self.cfg.account.fixed_lot
        initial_balance = self.cfg.account.initial_balance
        balance = initial_balance

        h1_ctx = self._compute_h1_context(h1_df)
        h4_ctx = self._compute_h4_context(h4_df)
        df = self._attach_context(exec_df, h1_ctx, h4_ctx)

        open_trade: Optional[Trade] = None
        closed_trades: list[Trade] = []
        equity_curve: list[float] = []

        for i in range(len(df)):
            row = df.iloc[i]
            t = pd.Timestamp(row["time"]).to_pydatetime()

            if open_trade is not None:
                low = float(row["Low"])
                high = float(row["High"])

                if open_trade.side == "buy":
                    sl_hit = low <= open_trade.stop_loss
                    tp_hit = high >= open_trade.take_profit
                else:
                    sl_hit = high >= open_trade.stop_loss
                    tp_hit = low <= open_trade.take_profit

                if sl_hit or tp_hit:
                    if sl_hit and tp_hit:
                        exit_price = open_trade.stop_loss
                        result = "SL"
                    elif sl_hit:
                        exit_price = open_trade.stop_loss
                        result = "SL"
                    else:
                        exit_price = open_trade.take_profit
                        result = "TP"

                    closed = self._close_trade(
                        trade=open_trade,
                        exit_price=exit_price,
                        exit_time=t,
                        exit_index=i,
                        result=result,
                        balance_before=balance,
                    )
                    balance += closed.pnl_usd
                    closed_trades.append(closed)
                    open_trade = None

            h1_context = {
                "structure_bullish": bool(row["structure_bullish"]),
                "structure_bearish": bool(row["structure_bearish"]),
            }
            h4_context = {
                "trend_bullish": bool(row["trend_bullish"]),
                "trend_bearish": bool(row["trend_bearish"]),
            }

            if open_trade is None:
                signal: Optional[TradeSignal] = strategy.process_bar(df, i, h1_context, h4_context)
                if signal is not None:
                    if ai_inference is not None and self.cfg.ai.enabled:
                        features = np.array(
                            [
                                float(row["Open"]),
                                float(row["High"]),
                                float(row["Low"]),
                                float(row["Close"]),
                                float(row["Volume"]),
                            ],
                            dtype=np.float32,
                        )
                        label, confidence = ai_inference.predict_feature_vector(features)
                        if label == "bad_setup" or confidence < self.cfg.ai.confidence_threshold:
                            signal = None

                if signal is not None:
                    open_trade = Trade(
                        side=signal.side,
                        entry_time=t,
                        entry_index=i,
                        entry_price=signal.entry_price,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        lot_size=lot,
                        rr_target=signal.rr,
                        reason=signal.reason,
                        session=self._classify_session(row["time"]),
                    )

            floating = 0.0
            if open_trade is not None:
                floating = self._pnl_usd(open_trade.side, open_trade.entry_price, float(row["Close"]), open_trade.lot_size)
            equity_curve.append(balance + floating)

        if open_trade is not None:
            last = df.iloc[-1]
            close_trade = self._close_trade(
                trade=open_trade,
                exit_price=float(last["Close"]),
                exit_time=pd.Timestamp(last["time"]).to_pydatetime(),
                exit_index=len(df) - 1,
                result="FORCED_CLOSE",
                balance_before=balance,
            )
            balance += close_trade.pnl_usd
            closed_trades.append(close_trade)

        metrics = self._compute_metrics(timeframe, initial_balance, balance, closed_trades, equity_curve)
        trades_df = pd.DataFrame([asdict(t) for t in closed_trades]) if closed_trades else pd.DataFrame()

        return {
            "timeframe": timeframe,
            "metrics": metrics,
            "trades_df": trades_df,
            "equity_curve": equity_curve,
            "candles_df": df,
            "orderblocks": strategy.orderblocks,
        }

    def _compute_metrics(
        self,
        timeframe: str,
        initial_balance: float,
        final_balance: float,
        trades: list[Trade],
        equity_curve: list[float],
    ) -> BacktestMetrics:
        if not trades:
            return BacktestMetrics(
                timeframe=timeframe,
                initial_balance=initial_balance,
                final_balance=final_balance,
                total_pnl_usd=final_balance - initial_balance,
                total_return_pct=((final_balance - initial_balance) / initial_balance) * 100 if initial_balance else 0.0,
                win_rate=0.0,
                profit_factor=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                total_trades=0,
                wins=0,
                losses=0,
                avg_rr=0.0,
                consecutive_wins_max=0,
                consecutive_losses_max=0,
                buy_trades=0,
                sell_trades=0,
                monthly_stats={},
                session_stats={},
            )

        pnl = np.array([t.pnl_usd for t in trades], dtype=np.float64)
        wins = int((pnl > 0).sum())
        losses = int((pnl <= 0).sum())
        total = len(trades)

        win_rate = (wins / total) * 100.0
        gross_profit = float(pnl[pnl > 0].sum()) if np.any(pnl > 0) else 0.0
        gross_loss = float(abs(pnl[pnl <= 0].sum())) if np.any(pnl <= 0) else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        eq = np.array(equity_curve if equity_curve else [initial_balance], dtype=np.float64)
        roll = np.maximum.accumulate(eq)
        drawdowns = np.where(roll > 0, (eq - roll) / roll * 100.0, 0.0)
        max_dd = abs(float(drawdowns.min())) if len(drawdowns) else 0.0

        returns = np.diff(eq) / np.where(eq[:-1] == 0, 1.0, eq[:-1]) if len(eq) > 1 else np.array([0.0])
        sharpe = float(np.sqrt(252) * (returns.mean() / returns.std())) if returns.std() > 1e-12 else 0.0

        rr_values = [t.rr_realized for t in trades]
        avg_rr = float(np.mean(rr_values)) if rr_values else 0.0

        cons_w, cons_l, cur_w, cur_l = 0, 0, 0, 0
        for t in trades:
            if t.pnl_usd > 0:
                cur_w += 1
                cur_l = 0
            else:
                cur_l += 1
                cur_w = 0
            cons_w = max(cons_w, cur_w)
            cons_l = max(cons_l, cur_l)

        buy_trades = sum(1 for t in trades if t.side == "buy")
        sell_trades = sum(1 for t in trades if t.side == "sell")

        monthly: dict[str, dict[str, float]] = {}
        session_stats: dict[str, dict[str, float]] = {}
        for t in trades:
            if t.exit_time is None:
                continue
            month_key = t.exit_time.strftime("%Y-%m")
            monthly.setdefault(month_key, {"trades": 0.0, "pnl_usd": 0.0})
            monthly[month_key]["trades"] += 1.0
            monthly[month_key]["pnl_usd"] += t.pnl_usd

            sess = t.session
            session_stats.setdefault(sess, {"trades": 0.0, "pnl_usd": 0.0})
            session_stats[sess]["trades"] += 1.0
            session_stats[sess]["pnl_usd"] += t.pnl_usd

        return BacktestMetrics(
            timeframe=timeframe,
            initial_balance=initial_balance,
            final_balance=final_balance,
            total_pnl_usd=final_balance - initial_balance,
            total_return_pct=((final_balance - initial_balance) / initial_balance) * 100 if initial_balance else 0.0,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown_pct=max_dd,
            sharpe_ratio=sharpe,
            total_trades=total,
            wins=wins,
            losses=losses,
            avg_rr=avg_rr,
            consecutive_wins_max=cons_w,
            consecutive_losses_max=cons_l,
            buy_trades=buy_trades,
            sell_trades=sell_trades,
            monthly_stats=monthly,
            session_stats=session_stats,
        )
