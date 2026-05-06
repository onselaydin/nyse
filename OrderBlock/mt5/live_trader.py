from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd

from config import AppConfig
from mt5.connector import MT5Connector
from strategy.orderblock_strategy import OrderBlockStrategy


@dataclass(slots=True)
class LivePositionTrack:
    ticket: int
    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: datetime
    magic: int
    comment: str


class MT5LiveTrader:
    """
    M15 için bağımsız canlı/demo trader.
    - Sadece kendi magic number/comment işlemlerini takip eder.
    - Manuel kapatma (MT5 terminalinden) tespit edilip loglanır.
    - Trailing SL varsayılan açık (B).
    """

    MAGIC = 990015
    COMMENT = "OrderBlock-M15"

    def __init__(self, cfg: AppConfig, logger):
        self.cfg = cfg
        self.logger = logger
        self.conn = MT5Connector(cfg, logger)
        self.strategy = OrderBlockStrategy(cfg, logger)
        self.symbol = cfg.strategy.symbol
        self.timeframe = "M15"
        self.last_bar_time: Optional[pd.Timestamp] = None
        self.active_ticket: Optional[int] = None
        self.track: dict[int, LivePositionTrack] = {}
        self.audit_csv = cfg.paths.logs_dir / "live_trade_audit.csv"
        self.audit_csv.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> bool:
        return self.conn.connect()

    def shutdown(self) -> None:
        self.conn.shutdown()

    def _write_audit(self, row: dict) -> None:
        df = pd.DataFrame([row])
        header = not self.audit_csv.exists()
        df.to_csv(self.audit_csv, mode="a", header=header, index=False)

    def _fetch_recent(self, bars: int = 400) -> pd.DataFrame:
        tf = mt5.TIMEFRAME_M15
        rates = mt5.copy_rates_from_pos(self.symbol, tf, 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"M15 veri çekilemedi: {mt5.last_error()}")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.rename(
            columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "tick_volume": "Volume"},
            inplace=True,
        )
        return df[["time", "Open", "High", "Low", "Close", "Volume"]].copy()

    def _fetch_h1_h4(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        h1 = self.conn.fetch_rates(self.symbol, "H1", months=1)
        h4 = self.conn.fetch_rates(self.symbol, "H4", months=1)
        return h1, h4

    def _has_own_open_position(self) -> bool:
        positions = mt5.positions_get(symbol=self.symbol)
        if positions is None:
            return False
        for p in positions:
            if int(p.magic) == self.MAGIC and str(p.comment) == self.COMMENT:
                self.active_ticket = int(p.ticket)
                return True
        self.active_ticket = None
        return False

    def _send_order(self, side: str, sl: float, tp: float) -> Optional[int]:
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            self.logger.error("Tick bilgisi alınamadı.")
            return None

        volume = float(self.cfg.account.fixed_lot)
        if side == "buy":
            order_type = mt5.ORDER_TYPE_BUY
            price = float(tick.ask)
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = float(tick.bid)

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
            "magic": self.MAGIC,
            "comment": self.COMMENT,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        if res is None:
            self.logger.error("order_send yanıt vermedi: %s", mt5.last_error())
            return None

        if res.retcode != mt5.TRADE_RETCODE_DONE:
            self.logger.error("Emir reddedildi | retcode=%s", res.retcode)
            return None

        self.logger.info("EMİR AÇILDI | side=%s | ticket=%s | price=%.5f", side.upper(), res.order, price)
        self._write_audit(
            {
                "time": datetime.utcnow().isoformat(),
                "event": "OPEN",
                "ticket": int(res.order),
                "side": side,
                "price": price,
                "sl": sl,
                "tp": tp,
                "volume": volume,
            }
        )
        return int(res.order)

    def _sync_manual_closes(self) -> None:
        open_positions = mt5.positions_get(symbol=self.symbol)
        open_tickets = set()
        if open_positions is not None:
            for p in open_positions:
                if int(p.magic) == self.MAGIC and str(p.comment) == self.COMMENT:
                    open_tickets.add(int(p.ticket))

        tracked = list(self.track.keys())
        for ticket in tracked:
            if ticket not in open_tickets:
                tr = self.track.pop(ticket)
                self.logger.warning("MANUEL/KARŞI KAPANMA TESPİT | ticket=%s | side=%s", ticket, tr.side.upper())
                self._write_audit(
                    {
                        "time": datetime.utcnow().isoformat(),
                        "event": "MANUAL_OR_EXTERNAL_CLOSE",
                        "ticket": ticket,
                        "side": tr.side,
                        "price": None,
                        "sl": tr.stop_loss,
                        "tp": tr.take_profit,
                        "volume": self.cfg.account.fixed_lot,
                    }
                )
                if self.active_ticket == ticket:
                    self.active_ticket = None

    def _apply_trailing(self) -> None:
        if self.active_ticket is None:
            return

        pos = mt5.positions_get(ticket=self.active_ticket)
        if not pos:
            return
        p = pos[0]

        entry = float(p.price_open)
        cur_sl = float(p.sl)
        tp = float(p.tp)
        side = "buy" if int(p.type) == mt5.POSITION_TYPE_BUY else "sell"

        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return

        price = float(tick.bid if side == "buy" else tick.ask)

        risk = abs(entry - cur_sl) if cur_sl > 0 else 0.0
        if risk <= 0:
            return

        one_r = risk
        step = one_r * 0.5

        if side == "buy":
            if price >= entry + one_r:
                new_sl = max(cur_sl, entry)
            else:
                return
            while new_sl + step < price - step:
                new_sl += step
        else:
            if price <= entry - one_r:
                new_sl = min(cur_sl if cur_sl > 0 else entry, entry)
            else:
                return
            while new_sl - step > price + step:
                new_sl -= step

        if abs(new_sl - cur_sl) < 1e-6:
            return

        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self.symbol,
            "position": int(p.ticket),
            "sl": float(new_sl),
            "tp": float(tp),
            "magic": self.MAGIC,
            "comment": self.COMMENT,
        }
        res = mt5.order_send(req)
        if res is None:
            return
        if res.retcode == mt5.TRADE_RETCODE_DONE:
            self.logger.info("TRAILING SL GÜNCELLENDİ | ticket=%s | old=%.5f | new=%.5f", p.ticket, cur_sl, new_sl)
            self._write_audit(
                {
                    "time": datetime.utcnow().isoformat(),
                    "event": "TRAILING_SL_UPDATE",
                    "ticket": int(p.ticket),
                    "side": side,
                    "price": price,
                    "sl": new_sl,
                    "tp": tp,
                    "volume": float(p.volume),
                }
            )

    def run_loop(self, poll_seconds: int = 5) -> None:
        self.logger.info("M15 canlı trader başlatıldı | Symbol=%s | Magic=%s", self.symbol, self.MAGIC)

        while True:
            try:
                m15 = self._fetch_recent(500)
                h1, h4 = self._fetch_h1_h4()

                if len(m15) < 50:
                    time.sleep(poll_seconds)
                    continue

                current_bar_time = pd.Timestamp(m15.iloc[-1]["time"])
                if self.last_bar_time is not None and current_bar_time <= self.last_bar_time:
                    self._sync_manual_closes()
                    self._apply_trailing()
                    time.sleep(poll_seconds)
                    continue

                self.last_bar_time = current_bar_time

                i = len(m15) - 2
                h1_context = {"structure_bullish": True, "structure_bearish": True}
                h4_context = {"trend_bullish": True, "trend_bearish": True}

                signal = self.strategy.process_bar(m15, i, h1_context, h4_context)

                self._sync_manual_closes()
                self._apply_trailing()

                if signal is None:
                    time.sleep(poll_seconds)
                    continue

                if self._has_own_open_position():
                    self.logger.info("Açık pozisyon var, yeni sinyal atlandı.")
                    time.sleep(poll_seconds)
                    continue

                ticket = self._send_order(signal.side, signal.stop_loss, signal.take_profit)
                if ticket is not None:
                    self.active_ticket = ticket
                    self.track[ticket] = LivePositionTrack(
                        ticket=ticket,
                        side=signal.side,
                        entry_price=signal.entry_price,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        opened_at=datetime.utcnow(),
                        magic=self.MAGIC,
                        comment=self.COMMENT,
                    )

            except KeyboardInterrupt:
                self.logger.info("Canlı trader kullanıcı tarafından durduruldu.")
                break
            except Exception as exc:
                self.logger.exception("Canlı trader döngü hatası: %s", exc)
                time.sleep(poll_seconds)
