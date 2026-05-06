from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(slots=True)
class OrderBlockZone:
    direction: str  # "bullish" | "bearish"
    created_index: int
    low: float
    high: float
    bos_index: int
    active: bool = True


@dataclass(slots=True)
class TradeSignal:
    side: str  # "buy" | "sell"
    index: int
    entry_price: float
    stop_loss: float
    take_profit: float
    rr: float
    reason: str


class OrderBlockStrategy:
    POINT = 0.00001

    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.logger = logger

        self.swing_highs: list[tuple[int, float]] = []
        self.swing_lows: list[tuple[int, float]] = []
        self.orderblocks: list[OrderBlockZone] = []

    def process_bar(
        self,
        df_exec: pd.DataFrame,
        i: int,
        h1_context: Optional[dict] = None,
        h4_context: Optional[dict] = None,
    ) -> Optional[TradeSignal]:
        self._detect_swings(df_exec, i)
        self._detect_orderblock(df_exec, i, "bullish")
        self._detect_orderblock(df_exec, i, "bearish")
        return self._try_entry(df_exec, i, h1_context, h4_context)

    def _detect_swings(self, df: pd.DataFrame, i: int) -> None:
        s = int(self.cfg.strategy.pivot_sensitivity)
        c = i - s
        if c < s or c + s >= len(df):
            return
        w = df.iloc[c - s : c + s + 1]
        row = df.iloc[c]

        if row["Low"] <= w["Low"].min():
            if not self.swing_lows or self.swing_lows[-1][0] != c:
                self.swing_lows.append((c, float(row["Low"])))

        if row["High"] >= w["High"].max():
            if not self.swing_highs or self.swing_highs[-1][0] != c:
                self.swing_highs.append((c, float(row["High"])))

    def _candle_body(self, row: pd.Series) -> float:
        return abs(float(row["Close"]) - float(row["Open"]))

    def _candle_range(self, row: pd.Series) -> float:
        return max(1e-10, float(row["High"]) - float(row["Low"]))

    def _is_bos(self, df: pd.DataFrame, i: int, direction: str) -> bool:
        if direction == "bullish":
            if not self.swing_highs:
                return False
            return float(df.iloc[i]["Close"]) > self.swing_highs[-1][1]
        if not self.swing_lows:
            return False
        return float(df.iloc[i]["Close"]) < self.swing_lows[-1][1]

    def _find_last_opposite_candle(self, df: pd.DataFrame, i: int, direction: str) -> Optional[int]:
        lookback = 8
        start = max(1, i - lookback)
        for idx in range(i - 1, start - 1, -1):
            row = df.iloc[idx]
            if direction == "bullish" and float(row["Close"]) < float(row["Open"]):
                return idx
            if direction == "bearish" and float(row["Close"]) > float(row["Open"]):
                return idx
        return None

    def _detect_orderblock(self, df: pd.DataFrame, i: int, direction: str) -> None:
        if i < 5:
            return

        row = df.iloc[i]
        body = self._candle_body(row)
        rng = self._candle_range(row)
        body_ratio = body / rng
        displacement_points = body / self.POINT

        if direction == "bullish":
            directional = float(row["Close"]) > float(row["Open"])
        else:
            directional = float(row["Close"]) < float(row["Open"])

        if not directional:
            return
        if body_ratio < self.cfg.strategy.momentum_body_to_range_min:
            return
        if displacement_points < self.cfg.strategy.min_displacement_points:
            return
        if not self._is_bos(df, i, direction):
            return

        last_opposite = self._find_last_opposite_candle(df, i, direction)
        if last_opposite is None:
            return

        ob_row = df.iloc[last_opposite]
        zone = OrderBlockZone(
            direction=direction,
            created_index=last_opposite,
            low=float(ob_row["Low"]),
            high=float(ob_row["High"]),
            bos_index=i,
            active=True,
        )
        self.orderblocks.append(zone)

    def _in_session(self, ts: pd.Timestamp) -> bool:
        if not self.cfg.session.enabled:
            return True

        ts_utc = pd.Timestamp(ts).tz_convert("UTC") if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).tz_localize("UTC")
        hour = int((ts_utc + pd.Timedelta(hours=self.cfg.session.utc_offset_hours)).hour)

        l = self.cfg.session.london
        n = self.cfg.session.new_york
        in_london = l.start_hour_utc <= hour <= l.end_hour_utc
        in_new_york = n.start_hour_utc <= hour <= n.end_hour_utc
        return in_london or in_new_york

    def _passes_mtf(self, direction: str, h1_context: Optional[dict], h4_context: Optional[dict]) -> bool:
        if h1_context is None or h4_context is None:
            return False

        if direction == "bullish":
            return bool(h4_context.get("trend_bullish", False)) and bool(h1_context.get("structure_bullish", False))
        return bool(h4_context.get("trend_bearish", False)) and bool(h1_context.get("structure_bearish", False))

    def _is_wick_rejection(self, row: pd.Series, direction: str) -> bool:
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        body = max(1e-10, abs(c - o))
        if direction == "bullish":
            lower_wick = min(o, c) - l
            return lower_wick / body >= self.cfg.strategy.wick_to_body_ratio_min
        upper_wick = h - max(o, c)
        return upper_wick / body >= self.cfg.strategy.wick_to_body_ratio_min

    def _is_momentum_confirmation(self, row: pd.Series, direction: str) -> bool:
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        body = abs(c - o)
        rng = max(1e-10, h - l)
        body_ratio = body / rng
        if direction == "bullish":
            return c > o and body_ratio >= self.cfg.strategy.momentum_body_to_range_min
        return c < o and body_ratio >= self.cfg.strategy.momentum_body_to_range_min

    def _try_entry(
        self,
        df: pd.DataFrame,
        i: int,
        h1_context: Optional[dict],
        h4_context: Optional[dict],
    ) -> Optional[TradeSignal]:
        if i < 10:
            return None

        row = df.iloc[i]
        if not self._in_session(row["time"]):
            return None

        rr = float(self.cfg.risk.rr_targets[0])
        sl_buffer = float(self.cfg.risk.sl_buffer_points) * self.POINT

        for ob in reversed(self.orderblocks):
            if not ob.active:
                continue

            touched = float(row["Low"]) <= ob.high and float(row["High"]) >= ob.low
            if not touched:
                continue

            if not self._passes_mtf(ob.direction, h1_context, h4_context):
                continue

            wick_ok = self.cfg.strategy.allow_wick_confirmation and self._is_wick_rejection(row, ob.direction)
            momentum_ok = self.cfg.strategy.allow_momentum_confirmation and self._is_momentum_confirmation(row, ob.direction)
            if not (wick_ok or momentum_ok):
                continue

            entry = float(row["Close"])
            if ob.direction == "bullish":
                sl = min(float(row["Low"]), ob.low) - sl_buffer
                risk = entry - sl
                if risk <= 0:
                    continue
                tp = entry + (risk * rr)
                signal = TradeSignal("buy", i, entry, sl, tp, rr, "Bullish OB + Onay")
            else:
                sl = max(float(row["High"]), ob.high) + sl_buffer
                risk = sl - entry
                if risk <= 0:
                    continue
                tp = entry - (risk * rr)
                signal = TradeSignal("sell", i, entry, sl, tp, rr, "Bearish OB + Onay")

            ob.active = False
            return signal

        return None
