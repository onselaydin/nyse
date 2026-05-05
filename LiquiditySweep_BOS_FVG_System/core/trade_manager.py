from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Iterable

import pandas as pd

from .models import Trade


class TradeManager:
    """Pozisyon açma/kapama ve PnL hesaplama işlemleri."""

    PIP_VALUE_PER_LOT_EURUSD = 10.0
    POINTS_PER_PIP = 10

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        fixed_lot: float,
        commission_per_lot_usd: float = 0.0,
        swap_long_pips_per_night: float = 0.0,
        swap_short_pips_per_night: float = 0.0,
        apply_commission: bool = True,
        apply_swap: bool = True,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.fixed_lot = fixed_lot
        self.commission_per_lot_usd = commission_per_lot_usd
        self.swap_long_pips_per_night = swap_long_pips_per_night
        self.swap_short_pips_per_night = swap_short_pips_per_night
        self.apply_commission = apply_commission
        self.apply_swap = apply_swap
        self.open_trades: list[Trade] = []
        self.closed_trades: list[Trade] = []
        self._counter = 0

    def _next_trade_id(self) -> str:
        self._counter += 1
        return f"TRD-{self.timeframe}-{self._counter:05d}"

    def can_open_trade(self, max_open_positions: int) -> bool:
        return len(self.open_trades) < max_open_positions

    def open_buy_trade(
        self,
        index: int,
        time: datetime,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        spread_points: float,
        reason: str,
    ) -> Trade:
        trade = Trade(
            id=self._next_trade_id(),
            symbol=self.symbol,
            timeframe=self.timeframe,
            side="buy",
            open_index=index,
            open_time=time,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            lot_size=self.fixed_lot,
            spread_points=spread_points,
            reason=reason,
        )
        self.open_trades.append(trade)
        return trade

    def open_sell_trade(
        self,
        index: int,
        time: datetime,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        spread_points: float,
        reason: str,
    ) -> Trade:
        trade = Trade(
            id=self._next_trade_id(),
            symbol=self.symbol,
            timeframe=self.timeframe,
            side="sell",
            open_index=index,
            open_time=time,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            lot_size=self.fixed_lot,
            spread_points=spread_points,
            reason=reason,
        )
        self.open_trades.append(trade)
        return trade

    def update_open_trades(self, index: int, time: datetime, high: float, low: float) -> list[Trade]:
        """
        Açık işlemlerin bu mum içinde TP/SL'e değip değmediğini kontrol eder.
        Aynı mumda hem SL hem TP geçilirse konservatif yaklaşım için önce SL varsayılır.
        """

        closed_now: list[Trade] = []
        still_open: list[Trade] = []

        for trade in self.open_trades:
            if trade.side == "buy":
                sl_hit = low <= trade.stop_loss
                tp_hit = high >= trade.take_profit
            elif trade.side == "sell":
                sl_hit = high >= trade.stop_loss
                tp_hit = low <= trade.take_profit
            else:
                still_open.append(trade)
                continue

            if sl_hit:
                self._close_trade(trade, index, time, trade.stop_loss, "SL")
                closed_now.append(trade)
            elif tp_hit:
                self._close_trade(trade, index, time, trade.take_profit, "TP")
                closed_now.append(trade)
            else:
                still_open.append(trade)

        self.open_trades = still_open
        self.closed_trades.extend(closed_now)
        return closed_now

    def _close_trade(
        self,
        trade: Trade,
        index: int,
        time: datetime,
        close_price: float,
        close_reason: str,
    ) -> None:
        trade.status = "closed"
        trade.close_index = index
        trade.close_time = time
        trade.close_price = close_price
        trade.close_reason = close_reason

        if trade.side == "buy":
            price_diff = close_price - trade.entry_price
            risk_distance = trade.entry_price - trade.stop_loss
        else:
            price_diff = trade.entry_price - close_price
            risk_distance = trade.stop_loss - trade.entry_price

        pips = price_diff * 10000
        pnl = pips * (self.PIP_VALUE_PER_LOT_EURUSD * trade.lot_size)

        # Spread maliyeti: pip bazında işlem sonucundan düşülür.
        spread_pips = trade.spread_points / self.POINTS_PER_PIP
        spread_cost = spread_pips * (self.PIP_VALUE_PER_LOT_EURUSD * trade.lot_size)
        pnl -= spread_cost

        # Komisyon: giriş + çıkış round-turn toplam (lot başına sabit USD).
        commission = 0.0
        if self.apply_commission and self.commission_per_lot_usd > 0:
            commission = self.commission_per_lot_usd * trade.lot_size
            pnl -= commission
        trade.commission_usd = commission

        # Swap: gecelik tutma maliyeti (pozitif = kazanç, negatif = maliyet).
        swap = 0.0
        if self.apply_swap and trade.open_time and trade.close_time:
            nights = (trade.close_time.date() - trade.open_time.date()).days
            trade.nights_held = max(nights, 0)
            if trade.nights_held > 0:
                swap_pips_per_night = (
                    self.swap_long_pips_per_night
                    if trade.side == "buy"
                    else self.swap_short_pips_per_night
                )
                swap = (
                    swap_pips_per_night
                    * trade.nights_held
                    * self.PIP_VALUE_PER_LOT_EURUSD
                    * trade.lot_size
                )
                pnl += swap
        trade.swap_usd = swap

        if risk_distance > 0:
            trade.rr_realized = price_diff / risk_distance
        else:
            trade.rr_realized = 0.0

        trade.pnl_usd = pnl

    def force_close_all(self, index: int, time: datetime, close_price: float) -> list[Trade]:
        closed = []
        for trade in self.open_trades:
            self._close_trade(trade, index, time, close_price, "Backtest Sonu")
            closed.append(trade)

        self.open_trades = []
        self.closed_trades.extend(closed)
        return closed

    def trades_to_dataframe(self, trades: Iterable[Trade]) -> pd.DataFrame:
        rows = []
        for trade in trades:
            payload = asdict(trade)
            rows.append(payload)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        return df
