from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

import pandas as pd

from core.indicators import candle_body_points
from core.models import BOSSignal, FVGZone, LiquiditySweepSignal, SwingPoint


class LiquiditySweepBOSFVGStrategy:
    """
    SMC akışını yönlü (bullish + bearish) şekilde uygular.

    Long akış:
    1) Low liquidity sweep
    2) Bullish BOS (close şartı)
    3) Displacement filtresi
    4) Bullish FVG
    5) FVG retest + bullish reaction

    Short akış:
    1) High liquidity sweep
    2) Bearish BOS (close şartı)
    3) Displacement filtresi
    4) Bearish FVG
    5) FVG retest + bearish reaction
    """

    POINT_VALUE = 0.00001

    def __init__(self, strategy_cfg: dict[str, Any], logger):
        self.cfg = strategy_cfg
        self.logger = logger

        self.swing_points: list[SwingPoint] = []
        self.swing_lows: list[SwingPoint] = []
        self.swing_highs: list[SwingPoint] = []
        self.sweep_signals: list[LiquiditySweepSignal] = []
        self.bos_signals: list[BOSSignal] = []
        self.fvg_zones: list[FVGZone] = []
        self.debug_events: list[dict[str, Any]] = []

        self.used_swept_low_levels: set[int] = set()
        self.used_swept_high_levels: set[int] = set()

        self.pending_setup_long: dict[str, Any] = {}
        self.pending_setup_short: dict[str, Any] = {}

        self.enable_bullish = bool(self.cfg.get("direction", {}).get("enable_bullish", True))
        self.enable_bearish = bool(self.cfg.get("direction", {}).get("enable_bearish", True))

        self._fvg_counter = 0

    def process_bar(
        self,
        df: pd.DataFrame,
        i: int,
        htf_context: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Her mum geldiğinde yönlü sinyal zincirini adım adım çalıştırır."""

        self._detect_pivot_with_delay(df, i)
        self._update_fvg_mitigation(df, i)

        # Long setup akışı
        if self.enable_bullish:
            self._update_directional_setup(df, i, direction="bullish")

        # Short setup akışı
        if self.enable_bearish:
            self._update_directional_setup(df, i, direction="bearish")

        # Önce long sonra short kontrol edilir. Aynı mumda tek giriş üretmek için ilk yakalanan döndürülür.
        if self.enable_bullish:
            long_entry = self._try_generate_entry(df, i, htf_context, direction="bullish")
            if long_entry is not None:
                self.pending_setup_long = {}
                return long_entry

        if self.enable_bearish:
            short_entry = self._try_generate_entry(df, i, htf_context, direction="bearish")
            if short_entry is not None:
                self.pending_setup_short = {}
                return short_entry

        self._invalidate_stale_setup(df, i, direction="bullish")
        self._invalidate_stale_setup(df, i, direction="bearish")
        return None

    def _setup_ref(self, direction: str) -> dict[str, Any]:
        return self.pending_setup_long if direction == "bullish" else self.pending_setup_short

    def _set_setup_ref(self, direction: str, payload: dict[str, Any]) -> None:
        if direction == "bullish":
            self.pending_setup_long = payload
        else:
            self.pending_setup_short = payload

    def _update_directional_setup(self, df: pd.DataFrame, i: int, direction: str) -> None:
        sweep_signal = self._detect_liquidity_sweep(df, i, direction=direction)
        if sweep_signal is not None:
            self._set_setup_ref(
                direction,
                {
                    "sweep": sweep_signal,
                    "bos": None,
                    "fvg": None,
                    "created_index": i,
                },
            )

        setup = self._setup_ref(direction)
        if setup.get("sweep") is not None and setup.get("bos") is None:
            bos_signal = self._detect_bos(df, i, direction=direction)
            if bos_signal is not None:
                setup["bos"] = bos_signal

        new_fvg = self._detect_fvg(df, i, direction=direction)
        if (
            new_fvg is not None
            and setup.get("bos") is not None
            and setup.get("fvg") is None
            and new_fvg.created_index >= setup["bos"].index
            and new_fvg.direction == direction
        ):
            setup["fvg"] = new_fvg

    def _detect_pivot_with_delay(self, df: pd.DataFrame, i: int) -> None:
        """
        Pivot/fraktal tespiti için look-ahead bias önlemek adına gecikmeli teyit kullanılır.
        Örnek sensitivity=2 ise i anında i-2 mumunun pivot olup olmadığı teyit edilir.
        """

        sensitivity = int(self.cfg.get("pivot_sensitivity", 2))
        candidate = i - sensitivity
        if candidate < sensitivity:
            return
        if candidate + sensitivity >= len(df):
            return

        left = candidate - sensitivity
        right = candidate + sensitivity
        window = df.iloc[left : right + 1]
        center = df.iloc[candidate]

        center_low = center["Low"]
        center_high = center["High"]

        is_swing_low = center_low <= window["Low"].min()
        is_swing_high = center_high >= window["High"].max()

        existing_idx = {s.index for s in self.swing_points}
        if candidate in existing_idx:
            return

        if is_swing_low:
            sp = SwingPoint(
                index=candidate,
                time=pd.Timestamp(center["time"]).to_pydatetime(),
                price=float(center_low),
                kind="low",
            )
            self.swing_points.append(sp)
            self.swing_lows.append(sp)
            self.debug_events.append(
                {"index": candidate, "time": center["time"], "event": "swing_low", "price": center_low}
            )

        if is_swing_high:
            sp = SwingPoint(
                index=candidate,
                time=pd.Timestamp(center["time"]).to_pydatetime(),
                price=float(center_high),
                kind="high",
            )
            self.swing_points.append(sp)
            self.swing_highs.append(sp)
            self.debug_events.append(
                {"index": candidate, "time": center["time"], "event": "swing_high", "price": center_high}
            )

    def _detect_liquidity_sweep(
        self,
        df: pd.DataFrame,
        i: int,
        direction: str,
    ) -> Optional[LiquiditySweepSignal]:
        """
        Bullish sweep:
        - fitil son swing low altına iner, kapanış tekrar üstündedir.

        Bearish sweep:
        - fitil son swing high üstüne çıkar, kapanış tekrar altındadır.
        """

        candle = df.iloc[i]
        min_distance_points = float(self.cfg.get("min_sweep_distance_points", 5))

        if direction == "bullish":
            prior_lows = [sp for sp in self.swing_lows if sp.index < i]
            if not prior_lows:
                return None
            target = prior_lows[-1]
            if target.index in self.used_swept_low_levels:
                return None

            wick_break = candle["Low"] < target.price
            close_reclaim = candle["Close"] > target.price
            sweep_distance_points = (target.price - candle["Low"]) / self.POINT_VALUE

            if wick_break and close_reclaim and sweep_distance_points >= min_distance_points:
                signal = LiquiditySweepSignal(
                    index=i,
                    time=pd.Timestamp(candle["time"]).to_pydatetime(),
                    direction="bullish",
                    swept_swing_index=target.index,
                    swept_level=target.price,
                    wick_price=float(candle["Low"]),
                    close_price=float(candle["Close"]),
                    sweep_distance_points=float(sweep_distance_points),
                )
                self.sweep_signals.append(signal)
                self.used_swept_low_levels.add(target.index)
                self.debug_events.append(
                    {"index": i, "time": candle["time"], "event": "liquidity_sweep_bullish", "price": candle["Close"]}
                )
                self.logger.info(
                    "Bullish Sweep | index=%s | swept_level=%.5f | mesafe=%.2f point",
                    i,
                    target.price,
                    sweep_distance_points,
                )
                return signal
            return None

        prior_highs = [sp for sp in self.swing_highs if sp.index < i]
        if not prior_highs:
            return None
        target = prior_highs[-1]
        if target.index in self.used_swept_high_levels:
            return None

        wick_break = candle["High"] > target.price
        close_reject = candle["Close"] < target.price
        sweep_distance_points = (candle["High"] - target.price) / self.POINT_VALUE

        if wick_break and close_reject and sweep_distance_points >= min_distance_points:
            signal = LiquiditySweepSignal(
                index=i,
                time=pd.Timestamp(candle["time"]).to_pydatetime(),
                direction="bearish",
                swept_swing_index=target.index,
                swept_level=target.price,
                wick_price=float(candle["High"]),
                close_price=float(candle["Close"]),
                sweep_distance_points=float(sweep_distance_points),
            )
            self.sweep_signals.append(signal)
            self.used_swept_high_levels.add(target.index)
            self.debug_events.append(
                {"index": i, "time": candle["time"], "event": "liquidity_sweep_bearish", "price": candle["Close"]}
            )
            self.logger.info(
                "Bearish Sweep | index=%s | swept_level=%.5f | mesafe=%.2f point",
                i,
                target.price,
                sweep_distance_points,
            )
            return signal

        return None

    def _detect_bos(self, df: pd.DataFrame, i: int, direction: str) -> Optional[BOSSignal]:
        """
        BOS close şartı:
        - bullish: close > son swing high
        - bearish: close < son swing low
        """

        candle = df.iloc[i]
        body_points = abs(candle["Close"] - candle["Open"]) / self.POINT_VALUE

        if not self._passes_displacement(df, i, body_points):
            return None

        if direction == "bullish":
            prior_highs = [sp for sp in self.swing_highs if sp.index < i]
            if not prior_highs:
                return None
            target = prior_highs[-1]
            if not candle["Close"] > target.price:
                return None

            signal = BOSSignal(
                index=i,
                time=pd.Timestamp(candle["time"]).to_pydatetime(),
                direction="bullish",
                broken_swing_index=target.index,
                broken_level=target.price,
                close_price=float(candle["Close"]),
                body_size_points=float(body_points),
            )
            self.bos_signals.append(signal)
            self.debug_events.append(
                {"index": i, "time": candle["time"], "event": "bos_bullish", "price": candle["Close"]}
            )
            self.logger.info(
                "Bullish BOS | index=%s | kırılan seviye=%.5f | body=%.2f point",
                i,
                target.price,
                body_points,
            )
            return signal

        prior_lows = [sp for sp in self.swing_lows if sp.index < i]
        if not prior_lows:
            return None
        target = prior_lows[-1]
        if not candle["Close"] < target.price:
            return None

        signal = BOSSignal(
            index=i,
            time=pd.Timestamp(candle["time"]).to_pydatetime(),
            direction="bearish",
            broken_swing_index=target.index,
            broken_level=target.price,
            close_price=float(candle["Close"]),
            body_size_points=float(body_points),
        )
        self.bos_signals.append(signal)
        self.debug_events.append(
            {"index": i, "time": candle["time"], "event": "bos_bearish", "price": candle["Close"]}
        )
        self.logger.info(
            "Bearish BOS | index=%s | kırılan seviye=%.5f | body=%.2f point",
            i,
            target.price,
            body_points,
        )
        return signal

    def _passes_displacement(self, df: pd.DataFrame, i: int, current_body_points: float) -> bool:
        disp_cfg = self.cfg.get("displacement", {})
        if not disp_cfg.get("enabled", True):
            return True

        lookback = int(disp_cfg.get("lookback_candles", 5))
        multiplier = float(disp_cfg.get("body_multiplier", 1.2))

        start = max(0, i - lookback)
        if start == i:
            return True

        past = df.iloc[start:i].copy()
        if past.empty:
            return True

        avg_body = candle_body_points(past).mean()
        return current_body_points > (avg_body * multiplier)

    def _detect_fvg(self, df: pd.DataFrame, i: int, direction: str) -> Optional[FVGZone]:
        """
        ICT 3 mum FVG:
        - bullish: c1.high < c3.low
        - bearish: c1.low > c3.high
        """

        if i < 2:
            return None

        c1 = df.iloc[i - 2]
        c3 = df.iloc[i]
        min_fvg_size = float(self.cfg.get("min_fvg_size_points", 8))

        if direction == "bullish":
            is_gap = c1["High"] < c3["Low"]
            if not is_gap:
                return None
            lower = float(c1["High"])
            upper = float(c3["Low"])
            size_points = (upper - lower) / self.POINT_VALUE
            event_name = "fvg_bullish"
        else:
            is_gap = c1["Low"] > c3["High"]
            if not is_gap:
                return None
            lower = float(c3["High"])
            upper = float(c1["Low"])
            size_points = (upper - lower) / self.POINT_VALUE
            event_name = "fvg_bearish"

        if size_points < min_fvg_size:
            return None

        self._fvg_counter += 1
        zone = FVGZone(
            id=f"FVG-{self._fvg_counter:05d}",
            direction=direction,
            created_index=i,
            created_time=pd.Timestamp(c3["time"]).to_pydatetime(),
            lower=lower,
            upper=upper,
            size_points=float(size_points),
            active=True,
        )
        self.fvg_zones.append(zone)
        self.debug_events.append(
            {"index": i, "time": c3["time"], "event": event_name, "price": c3["Close"]}
        )
        self.logger.info(
            "%s FVG | index=%s | zone=[%.5f, %.5f] | size=%.2f point",
            direction.capitalize(),
            i,
            lower,
            upper,
            size_points,
        )
        return zone

    def _update_fvg_mitigation(self, df: pd.DataFrame, i: int) -> None:
        """Yöne göre FVG mitigasyon kontrolü yapar ve pasifler."""

        candle = df.iloc[i]
        for zone in self.fvg_zones:
            if not zone.active:
                continue

            if zone.direction == "bullish":
                mitigated = candle["Low"] <= zone.lower
                price = candle["Low"]
                event_name = "fvg_mitigated_bullish"
            else:
                mitigated = candle["High"] >= zone.upper
                price = candle["High"]
                event_name = "fvg_mitigated_bearish"

            if mitigated:
                zone.active = False
                zone.mitigated_index = i
                zone.mitigated_time = pd.Timestamp(candle["time"]).to_pydatetime()
                self.debug_events.append(
                    {"index": i, "time": candle["time"], "event": event_name, "price": price}
                )

    def _try_generate_entry(
        self,
        df: pd.DataFrame,
        i: int,
        htf_context: Optional[dict[str, Any]],
        direction: str,
    ) -> Optional[dict[str, Any]]:
        """Kurulum tamamlandıysa retrace+reaksiyon+filtre sonrası işlem sinyali üretir."""

        setup = self._setup_ref(direction)
        if not setup:
            return None
        if setup.get("sweep") is None or setup.get("bos") is None:
            return None

        zone: Optional[FVGZone] = setup.get("fvg")
        if zone is None or not zone.active:
            return None

        candle = df.iloc[i]

        if not self._passes_session_filter(candle["time"]):
            return None
        if not self._passes_htf_filter(htf_context, direction=direction):
            return None

        # Retest: mum aralığı FVG zonu ile kesişmeli.
        in_zone = candle["Low"] <= zone.upper and candle["High"] >= zone.lower
        if not in_zone:
            return None

        if not self._is_reaction_valid(candle, direction=direction):
            return None

        sweep: LiquiditySweepSignal = setup["sweep"]
        stop_loss = self._compute_stop_loss(df, i, sweep, zone, direction=direction)

        entry_price = float(candle["Close"])
        rr_target = float(self.cfg.get("risk", {}).get("rr_target", 2.0))

        if direction == "bullish":
            risk = entry_price - stop_loss
            if risk <= 0:
                return None
            take_profit = entry_price + (risk * rr_target)
            side = "buy"
            event_name = "entry_long"
            reason = "Bullish Sweep -> BOS -> FVG -> Retest -> Bullish Reaction"
        else:
            risk = stop_loss - entry_price
            if risk <= 0:
                return None
            take_profit = entry_price - (risk * rr_target)
            side = "sell"
            event_name = "entry_short"
            reason = "Bearish Sweep -> BOS -> FVG -> Retest -> Bearish Reaction"

        self.debug_events.append(
            {"index": i, "time": candle["time"], "event": event_name, "price": candle["Close"]}
        )

        return {
            "side": side,
            "index": i,
            "time": pd.Timestamp(candle["time"]).to_pydatetime(),
            "entry_price": entry_price,
            "stop_loss": float(stop_loss),
            "take_profit": float(take_profit),
            "reason": reason,
            "fvg_id": zone.id,
        }

    def _passes_session_filter(self, ts: pd.Timestamp) -> bool:
        session_cfg = self.cfg.get("session_filter", {})
        if not session_cfg.get("enabled", True):
            return True

        hour = pd.Timestamp(ts).tz_localize("UTC").hour if pd.Timestamp(ts).tzinfo is None else pd.Timestamp(ts).tz_convert("UTC").hour

        london = session_cfg.get("london", {})
        ny = session_cfg.get("new_york", {})

        in_london = london.get("start_hour_utc", 7) <= hour <= london.get("end_hour_utc", 11)
        in_ny = ny.get("start_hour_utc", 12) <= hour <= ny.get("end_hour_utc", 16)
        return in_london or in_ny

    def _passes_htf_filter(self, htf_context: Optional[dict[str, Any]], direction: str) -> bool:
        htf_cfg = self.cfg.get("htf_filter", {})
        if not htf_cfg.get("enabled", True):
            return True
        if htf_context is None:
            return False

        if direction == "bullish":
            structure = bool(htf_context.get("structure_bullish", False))
            ema_side = bool(htf_context.get("price_above_ema50", False))
        else:
            structure = bool(htf_context.get("structure_bearish", False))
            ema_side = bool(htf_context.get("price_below_ema50", False))

        return structure or ema_side

    def _is_reaction_valid(self, candle: pd.Series, direction: str) -> bool:
        entry_cfg = self.cfg.get("entry_confirmation", {})
        mode = entry_cfg.get("mode", "rejection_or_body")

        open_price = float(candle["Open"])
        close_price = float(candle["Close"])
        high = float(candle["High"])
        low = float(candle["Low"])

        body_points = abs(close_price - open_price) / self.POINT_VALUE
        min_body = float(entry_cfg.get("min_body_points", entry_cfg.get("min_bullish_body_points", 10)))
        min_wick_ratio = float(entry_cfg.get("min_rejection_wick_ratio", 1.2))

        if abs(close_price - open_price) == 0:
            wick_ratio = 0.0
        elif direction == "bullish":
            lower_wick = min(open_price, close_price) - low
            wick_ratio = lower_wick / abs(close_price - open_price)
        else:
            upper_wick = high - max(open_price, close_price)
            wick_ratio = upper_wick / abs(close_price - open_price)

        if direction == "bullish":
            directional_body = close_price > open_price
        else:
            directional_body = close_price < open_price

        enough_body = body_points >= min_body
        enough_rejection = wick_ratio >= min_wick_ratio

        if mode == "body_only":
            return directional_body and enough_body
        if mode == "rejection_only":
            return directional_body and enough_rejection

        return directional_body and (enough_body or enough_rejection)

    def _compute_stop_loss(
        self,
        df: pd.DataFrame,
        i: int,
        sweep: LiquiditySweepSignal,
        fvg: FVGZone,
        direction: str,
    ) -> float:
        risk_cfg = self.cfg.get("risk", {})
        sl_mode = risk_cfg.get("sl_mode", "below_sweep_low")
        buffer = 2 * self.POINT_VALUE

        if direction == "bullish":
            if sl_mode == "below_fvg":
                return fvg.lower - buffer
            if sl_mode == "below_recent_swing_low":
                lows = [sp.price for sp in self.swing_lows if sp.index < i]
                if lows:
                    return min(lows[-3:]) - buffer
            return sweep.wick_price - buffer

        if sl_mode == "above_fvg":
            return fvg.upper + buffer
        if sl_mode == "above_recent_swing_high":
            highs = [sp.price for sp in self.swing_highs if sp.index < i]
            if highs:
                return max(highs[-3:]) + buffer
        return sweep.wick_price + buffer

    def _invalidate_stale_setup(self, df: pd.DataFrame, i: int, direction: str) -> None:
        """Kurulum çok uzarsa veya sweep seviyesi kaybedilirse setup iptal edilir."""

        setup = self._setup_ref(direction)
        if not setup:
            return

        sweep: Optional[LiquiditySweepSignal] = setup.get("sweep")
        if sweep is None:
            return

        candle = df.iloc[i]
        if direction == "bullish" and candle["Close"] < sweep.wick_price:
            self._set_setup_ref(direction, {})
            return
        if direction == "bearish" and candle["Close"] > sweep.wick_price:
            self._set_setup_ref(direction, {})
            return

        max_bars = 60
        if i - setup.get("created_index", i) > max_bars:
            self._set_setup_ref(direction, {})

    def export_debug_events(self) -> pd.DataFrame:
        return pd.DataFrame(self.debug_events)

    def export_swings(self) -> pd.DataFrame:
        rows = [asdict(sp) for sp in self.swing_points]
        return pd.DataFrame(rows)

    def export_fvg(self) -> pd.DataFrame:
        rows = [asdict(z) for z in self.fvg_zones]
        return pd.DataFrame(rows)
