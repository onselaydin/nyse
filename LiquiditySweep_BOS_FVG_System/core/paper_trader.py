"""
Paper / Live Trading Modülü
============================
Bu modül, backtest stratejisini gerçek zamanlı MT5 hesabına bağlar.

MİMARİ AÇIKLAMA – Çoklu Timeframe:
------------------------------------
Her timeframe (M5, M15, H1, H4) TAMAMEN BAĞIMSIZ çalışır.
  - M15 sinyali → M15 işlemi açılır (MT5'e gönderilir)
  - H1 sinyali → H1 işlemi açılır (MT5'e gönderilir, ayrı magic number)
  - İki işlem aynı anda MT5'te açık olabilir; broker bunları bağımsız yönetir.

Canlı kullanım için ÖNERİLEN yaklaşım:
  - Tek bir yürütme TF seçin (örn. M15) ve `active_timeframes=["M15"]` yapın.
  - H1 yalnızca HTF filtresi olarak kullanılır (işlem değil), strategy_config'de
    htf_filter.enabled=true bırakın; bu durumda H1 kendi başına sinyal üretmez.

KULLANIM:
    python run_paper_trader.py --timeframes M15 --strategy-config config/strategy_config_optimized_no_htf.json
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5
import pandas as pd

from core.mt5_connector import MT5Connector, TIMEFRAME_MAP
from strategies.liquidity_sweep_bos_fvg import LiquiditySweepBOSFVGStrategy

# Her timeframe için benzersiz magic number → MT5'te işlemleri ayırt eder.
MAGIC_NUMBERS: dict[str, int] = {
    "M5":  10005,
    "M15": 10015,
    "H1":  10060,
    "H4":  10240,
}

ORDER_COMMENTS: dict[str, str] = {
    "M15": "SMC-M15",
    "M5": "SMC-M5",
    "H1": "SMC-H1",
    "H4": "SMC-H4",
}

# Timeframe başına polling aralıkları (saniye).
POLL_INTERVALS: dict[str, int] = {
    "M5":  30,
    "M15": 60,
    "H1":  120,
    "H4":  300,
}

# Timeframe'e göre kaç bar çekilir (strateji penceresi).
LOOKBACK_BARS: dict[str, int] = {
    "M5":  500,
    "M15": 500,
    "H1":  300,
    "H4":  200,
}


class PaperTrader:
    """
    Gerçek zamanlı MT5 paper/live trading motoru.

    Her aktif timeframe için ayrı strateji örneği tutar.
    Polling döngüsünde son N mum çekilir, strateji process_bar() çağrılır.
    Sinyal varsa MT5 order_send() ile emir gönderilir.
    """

    def __init__(
        self,
        project_root: Path,
        system_cfg: dict[str, Any],
        strategy_cfg: dict[str, Any],
        active_timeframes: list[str],
        logger: logging.Logger,
        dry_run: bool = True,
    ):
        self.project_root = project_root
        self.system_cfg = system_cfg
        self.strategy_cfg = strategy_cfg
        self.active_timeframes = active_timeframes
        self.logger = logger
        self.dry_run = dry_run  # True → emir gönderilmez, sadece log edilir.

        self.symbol: str = system_cfg["symbol"]
        self.lot: float = float(system_cfg["account"]["fixed_lot"])
        self.slippage: int = int(system_cfg.get("execution", {}).get("slippage_points", 2))

        self.mt5_conn = MT5Connector(logger)

        self.strategy_kinds: dict[str, str] = {tf: "liquidity" for tf in active_timeframes}

        # Son gönderilen sinyal saati → aynı bara tekrar sinyal göndermeyi önler.
        self._last_signal_time: dict[str, datetime] = {}

        # Sinyal sayacı: max_signals aşılınca döngü durur (0 = sınırsız).
        self.max_signals: int = 0
        self._total_signals: int = 0

        # Canlı pozisyon yönetimi (opsiyonel):
        # 1) break-even
        # 2) kısmi kar alma
        tm_cfg = self.strategy_cfg.get("trade_management", {})
        self.enable_break_even = bool(tm_cfg.get("enable_break_even", True))
        self.break_even_rr = float(tm_cfg.get("break_even_rr", 1.0))
        self.enable_partial_tp = bool(tm_cfg.get("enable_partial_tp", True))
        self.partial_tp_rr = float(tm_cfg.get("partial_tp_rr", 1.5))
        self.partial_close_ratio = float(tm_cfg.get("partial_close_ratio", 0.5))
        self.rr_target_overrides = dict(tm_cfg.get("rr_target_overrides", {}))

        # MT5 pozisyon yaşam döngüsü takibi (açılış/kapanış/manüel kapanış).
        self._tracked_positions: dict[int, dict[str, Any]] = {}
        self._audit_file = self.project_root / "logs" / "trade_audit.csv"
        self._ensure_audit_file()

    # ------------------------------------------------------------------
    # Bağlantı
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """MT5'e bağlanır. Başarısızsa False döner."""
        mt5_cfg = self.system_cfg.get("mt5", {})
        return self.mt5_conn.connect(
            login=mt5_cfg.get("login"),
            password=mt5_cfg.get("password"),
            server=mt5_cfg.get("server"),
            path=mt5_cfg.get("path"),
        )

    def disconnect(self) -> None:
        self.mt5_conn.shutdown()

    # ------------------------------------------------------------------
    # Polling döngüsü
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """
        Sonsuz polling döngüsü. Ctrl+C ile durdurulur.

        Her TF kendi aralığında bağımsız kontrol edilir:
          - M15 → 60 saniyede bir
          - H1  → 120 saniyede bir
        """
        self.logger.info(
            "Paper trader başlatıldı | TF'ler: %s | Kuru Çalıştırma: %s",
            self.active_timeframes,
            self.dry_run,
        )

        last_check: dict[str, float] = {tf: 0.0 for tf in self.active_timeframes}

        try:
            while True:
                now = time.monotonic()
                for tf in self.active_timeframes:
                    interval = POLL_INTERVALS.get(tf, 60)
                    if now - last_check[tf] >= interval:
                        self._check_timeframe(tf)
                        last_check[tf] = now

                # Her döngüde pozisyon durumunu senkronize et (manuel/bot kapanışları yakala).
                self._sync_positions_and_log_closures()

                # Açık pozisyonlarda BE / partial TP kurallarını uygula.
                self._manage_open_positions()

                # max_signals dolunca otomatik durdur.
                if self.max_signals > 0 and self._total_signals >= self.max_signals:
                    self.logger.info(
                        "Hedef sinyal sayısına ulaşıldı (%d/%d). Paper trader durduruluyor.",
                        self._total_signals, self.max_signals,
                    )
                    break

                time.sleep(5)

        except KeyboardInterrupt:
            self.logger.info("Paper trader durduruldu (Ctrl+C).")
        finally:
            self.disconnect()

    # ------------------------------------------------------------------
    # Tek TF kontrol adımı
    # ------------------------------------------------------------------

    def _check_timeframe(self, tf: str) -> None:
        """
        Belirtilen timeframe için tüm mum geçmişini sıfırdan işler.

        Strateji state machine doğru çalışması için her polling döngüsünde
        tüm barlar baştan taranır; yalnızca son barın ürettiği sinyal kullanılır.
        """
        strategy_kind = self.strategy_kinds.get(tf, "liquidity")
        magic = MAGIC_NUMBERS.get(tf, 0)
        comment = ORDER_COMMENTS.get(tf, f"SMC-{tf}")
        
        self.logger.debug(
            "TF Kontrol | TF=%s | Strateji=%s | Magic=%d | Comment=%s | Lot=%.2f",
            tf, strategy_kind, magic, comment, self.lot,
        )
        
        df = self._fetch_bars(tf)
        if df is None or len(df) < 50:
            self.logger.warning("%s için yeterli veri yok, atlanıyor.", tf)
            return

        # H1/H4 bağlamı (log/filtre amaçlı).
        h1_ctx = self._build_h1_context()
        h4_ctx = self._build_h4_context()
        
        self.logger.debug(
            "MTF Bağlamı | TF=%s | H1_Bullish=%s | H1_Bearish=%s | H4_Bullish=%s | H4_Bearish=%s",
            tf,
            h1_ctx.get("structure_bullish", False),
            h1_ctx.get("structure_bearish", False),
            h4_ctx.get("trend_bullish", False),
            h4_ctx.get("trend_bearish", False),
        )

        # Her polling döngüsünde sıfırdan tara (look-ahead yok, state temiz).
        # Strateji iç logları (FVG/Sweep/BOS detayları) susturulur; sadece sinyal loglanır.
        silent_logger = logging.getLogger("paper_trader.silent")
        silent_logger.setLevel(logging.CRITICAL)
        
        self.logger.debug("Strateji Başlat | TF=%s | Liquidity Sweep BOS FVG", tf)
        strategy = LiquiditySweepBOSFVGStrategy(self.strategy_cfg, silent_logger)

        signal = None
        for i in range(len(df)):
            result = strategy.process_bar(df, i, h1_ctx)
            if result and i == len(df) - 1:
                signal = result  # Sadece son barın sinyali geçerli.
                self.logger.debug(
                    "Sinyal Üretildi | TF=%s | Strateji=%s | Yön=%s | Kaynak=BarIndex:%d",
                    tf, strategy_kind, result.get("side", "?"), i,
                )

        if not signal:
            self.logger.debug("Sinyal Yok | TF=%s | Strateji=%s", tf, strategy_kind)
            return

        signal = self._apply_rr_override(tf, signal)

        # Aynı bar için tekrar sinyal atlanır.
        sig_time: datetime = signal["time"]
        if self._last_signal_time.get(tf) == sig_time:
            self.logger.debug("Tekrarlanan Sinyal | TF=%s | BarTime=%s | ATLANIDI", tf, sig_time)
            return
        self._last_signal_time[tf] = sig_time

        self._total_signals += 1
        self.logger.info(
            "═" * 70,
        )
        self.logger.info(
            "SİNYAL #%d | %s %s | Strateji: %s | Magic: %d",
            self._total_signals,
            self.symbol, tf,
            strategy_kind.upper(),
            magic,
        )
        self.logger.info(
            "  Yön: %s | Giriş: %.5f | SL: %.5f | TP: %.5f",
            signal.get("side", "?").upper(),
            signal["entry_price"],
            signal["stop_loss"],
            signal["take_profit"],
        )
        self.logger.info(
            "  Sebep: %s | Lot: %.2f | Comment: %s",
            signal.get("reason", "N/A"),
            self.lot,
            comment,
        )
        self.logger.info("═" * 70)

        # Zaten bu TF için açık işlem var mı?
        if self._has_open_position(tf):
            self.logger.warning(
                "Açık Pozisyon Var | TF=%s | Magic=%d | Sinyal ATLANIDI",
                tf, magic,
            )
            return

        self._send_order(tf, signal)

    # ------------------------------------------------------------------
    # MT5 veri çekme
    # ------------------------------------------------------------------

    def _fetch_bars(self, tf: str) -> pd.DataFrame | None:
        """Son N mumu OHLCV DataFrame olarak döner."""
        mt5_tf = TIMEFRAME_MAP.get(tf)
        if mt5_tf is None:
            self.logger.error("Bilinmeyen timeframe: %s", tf)
            return None

        n = LOOKBACK_BARS.get(tf, 300)
        rates = mt5.copy_rates_from_pos(self.symbol, mt5_tf, 0, n)
        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_localize(None)
        df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "tick_volume": "Volume"}, inplace=True)
        return df.reset_index(drop=True)

    def _build_h1_context(self) -> dict[str, bool]:
        """H1 EMA50 ve yapısal yön bilgisini hesaplar."""
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H1, 0, 100)
        if rates is None or len(rates) < 52:
            return {"structure_bullish": False, "structure_bearish": False,
                    "price_above_ema50": False, "price_below_ema50": False}

        closes = [r["close"] for r in rates]
        ema50 = self._ema(closes, 50)
        last_close = closes[-1]
        prev_close = closes[-2]
        prev2_close = closes[-3]

        return {
            "structure_bullish": last_close > prev_close > prev2_close,
            "structure_bearish": last_close < prev_close < prev2_close,
            "price_above_ema50": last_close > ema50,
            "price_below_ema50": last_close < ema50,
        }

    def _build_h4_context(self) -> dict[str, bool]:
        """H4 yön filtresi için trend bağlamı hesaplar."""
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H4, 0, 100)
        if rates is None or len(rates) < 52:
            return {
                "trend_bullish": False,
                "trend_bearish": False,
                "price_above_ema50": False,
                "price_below_ema50": False,
            }

        closes = [r["close"] for r in rates]
        ema50 = self._ema(closes, 50)
        last_close = closes[-1]
        prev_close = closes[-2]
        prev2_close = closes[-3]

        return {
            "trend_bullish": (last_close > prev_close > prev2_close) and (last_close > ema50),
            "trend_bearish": (last_close < prev_close < prev2_close) and (last_close < ema50),
            "price_above_ema50": last_close > ema50,
            "price_below_ema50": last_close < ema50,
        }

    @staticmethod
    def _ema(closes: list[float], period: int) -> float:
        """Basit EMA hesaplaması (son değer döner)."""
        k = 2.0 / (period + 1)
        ema_val = sum(closes[:period]) / period
        for c in closes[period:]:
            ema_val = c * k + ema_val * (1 - k)
        return ema_val

    # ------------------------------------------------------------------
    # Açık pozisyon kontrolü
    # ------------------------------------------------------------------

    def _has_open_position(self, tf: str) -> bool:
        """Bu TF'ye ait magic number ile açık işlem var mı kontrol eder."""
        magic = MAGIC_NUMBERS.get(tf, 0)
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return False
        return any(p.magic == magic for p in positions)

    # ------------------------------------------------------------------
    # Emir gönderme
    # ------------------------------------------------------------------

    def _send_order(self, tf: str, signal: dict[str, Any]) -> None:
        """
        MT5'e market emri gönderir.

        dry_run=True ise emir gönderilmez, yalnızca loglanır.
        """
        side = signal.get("side", "buy")
        entry = float(signal["entry_price"])
        sl = float(signal["stop_loss"])
        tp = float(signal["take_profit"])
        magic = MAGIC_NUMBERS.get(tf, 0)

        order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL

        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    self.symbol,
            "volume":    self.lot,
            "type":      order_type,
            "price":     entry,
            "sl":        sl,
            "tp":        tp,
            "deviation": self.slippage,
            "magic":     magic,
            "comment":   ORDER_COMMENTS.get(tf, f"SMC-{tf}-{side[:1].upper()}"),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if self.dry_run:
            self.logger.info(
                "[KuruÇalıştırma] Emir GÖNDERİLMEDİ | %s %s | Magic=%d | Comment=%s | %s",
                self.symbol, tf, magic, request["comment"], side.upper(),
            )
            self.logger.info(
                "  Giriş=%.5f | SL=%.5f | TP=%.5f | Lot=%.2f",
                entry, sl, tp, self.lot,
            )
            return

        result = mt5.order_send(request)
        if result is None:
            self.logger.error(
                "order_send None | TF=%s | Magic=%d | Comment=%s | Hata=%s",
                tf, magic, request["comment"], mt5.last_error(),
            )
            self._append_audit_event(
                event_type="ORDER_SEND_FAIL",
                tf=tf,
                side=side.upper(),
                ticket=0,
                reason=f"order_send None | mt5_error={mt5.last_error()}",
                entry_price=entry,
                close_price=0.0,
                pnl=0.0,
            )
            return

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            self.logger.info(
                "Emir BAŞARILI | %s %s | Ticket=%d | Fiyat=%.5f",
                self.symbol, tf, result.order, result.price,
            )
            self.logger.info(
                "  Magic=%d | Comment=%s | Lot=%.2f | Side=%s",
                magic, request["comment"], self.lot, side.upper(),
            )
            self._append_audit_event(
                event_type="ORDER_SEND_OK",
                tf=tf,
                side=side.upper(),
                ticket=int(result.order),
                reason="Order accepted",
                entry_price=float(result.price),
                close_price=0.0,
                pnl=0.0,
            )
        else:
            self.logger.warning(
                "Emir BAŞARISIZ | TF=%s | Magic=%d | Kod=%d | %s",
                tf, magic, result.retcode, result.comment,
            )
            self._append_audit_event(
                event_type="ORDER_SEND_FAIL",
                tf=tf,
                side=side.upper(),
                ticket=0,
                reason=f"retcode={result.retcode} | {result.comment}",
                entry_price=entry,
                close_price=0.0,
                pnl=0.0,
            )

    def _apply_rr_override(self, tf: str, signal: dict[str, Any]) -> dict[str, Any]:
        """Timeframe bazlı RR override varsa TP değerini yeniden hesaplar."""
        if tf not in self.rr_target_overrides:
            return signal

        rr_override = float(self.rr_target_overrides[tf])
        entry = float(signal["entry_price"])
        sl = float(signal["stop_loss"])
        side = str(signal.get("side", "buy")).lower()
        risk = abs(entry - sl)
        if risk <= 0:
            return signal

        if side == "sell":
            tp_new = entry - (risk * rr_override)
        else:
            tp_new = entry + (risk * rr_override)

        old_tp = float(signal["take_profit"])
        signal["take_profit"] = tp_new
        self.logger.info(
            "TP OVERRIDE | %s %s | RR: %.2f | TP %.5f -> %.5f",
            self.symbol,
            tf,
            rr_override,
            old_tp,
            tp_new,
        )
        return signal

    def _ensure_audit_file(self) -> None:
        """İşlem denetim dosyası yoksa başlık satırıyla oluşturur."""
        self._audit_file.parent.mkdir(parents=True, exist_ok=True)
        if self._audit_file.exists():
            return
        header = (
            "time_utc,event_type,symbol,timeframe,side,ticket,reason,"
            "entry_price,close_price,volume,pnl,swap,commission\n"
        )
        self._audit_file.write_text(header, encoding="utf-8")

    def _append_audit_event(
        self,
        event_type: str,
        tf: str,
        side: str,
        ticket: int,
        reason: str,
        entry_price: float,
        close_price: float,
        pnl: float,
        volume: float = 0.0,
        swap: float = 0.0,
        commission: float = 0.0,
    ) -> None:
        """Pozisyon olaylarını CSV'e append eder."""
        safe_reason = str(reason).replace(",", " ;")
        line = (
            f"{datetime.now(timezone.utc).isoformat()},"
            f"{event_type},{self.symbol},{tf},{side},{ticket},{safe_reason},"
            f"{entry_price:.5f},{close_price:.5f},{volume:.2f},{pnl:.2f},{swap:.2f},{commission:.2f}\n"
        )
        with self._audit_file.open("a", encoding="utf-8") as f:
            f.write(line)

    def _sync_positions_and_log_closures(self) -> None:
        """
        MT5 açık pozisyon listesini takip eder:
        - Yeni açık pozisyonları kaydeder.
        - Kapanan pozisyonları history_deals ile neden/pnl bilgisiyle loglar.
        """
        positions = mt5.positions_get(symbol=self.symbol) or []
        live_positions = {int(p.ticket): p for p in positions}

        # Yeni açılan pozisyonlar.
        for ticket, pos in live_positions.items():
            if ticket in self._tracked_positions:
                continue
            tf = self._tf_from_magic(int(pos.magic))
            side = "BUY" if int(pos.type) == int(mt5.POSITION_TYPE_BUY) else "SELL"
            self._tracked_positions[ticket] = {
                "tf": tf,
                "side": side,
                "entry_price": float(pos.price_open),
                "volume": float(pos.volume),
                "initial_sl": float(pos.sl),
                "initial_tp": float(pos.tp),
                "be_done": False,
                "partial_done": False,
            }
            self.logger.info(
                "POZ AÇILDI | Ticket=%d | %s %s | Fiyat=%.5f | Lot=%.2f",
                ticket,
                self.symbol,
                tf,
                float(pos.price_open),
                float(pos.volume),
            )
            self._append_audit_event(
                event_type="POSITION_OPEN",
                tf=tf,
                side=side,
                ticket=ticket,
                reason="Detected in open positions",
                entry_price=float(pos.price_open),
                close_price=0.0,
                pnl=0.0,
                volume=float(pos.volume),
            )

        # Kapanan pozisyonlar.
        closed_tickets = [t for t in list(self._tracked_positions.keys()) if t not in live_positions]
        for ticket in closed_tickets:
            meta = self._tracked_positions.pop(ticket)
            close_info = self._get_closed_position_info(ticket)

            reason_label = close_info["reason_label"]
            pnl = close_info["pnl"]
            close_price = close_info["close_price"]
            swap = close_info["swap"]
            commission = close_info["commission"]

            if reason_label == "UNKNOWN_CLOSE":
                self.logger.warning(
                    "KAPANIŞ NEDENİ BELİRSİZ | Ticket=%d | TF=%s | SonDeal bulunamadı",
                    ticket,
                    meta["tf"],
                )

            self.logger.info(
                "POZ KAPANDI | Ticket=%d | %s %s | Sebep=%s | PnL=%.2f$ | Kapanış=%.5f",
                ticket,
                self.symbol,
                meta["tf"],
                reason_label,
                pnl,
                close_price,
            )

            self._append_audit_event(
                event_type="POSITION_CLOSE",
                tf=meta["tf"],
                side=meta["side"],
                ticket=ticket,
                reason=reason_label,
                entry_price=float(meta.get("entry_price", 0.0)),
                close_price=close_price,
                pnl=pnl,
                volume=float(meta.get("volume", 0.0)),
                swap=swap,
                commission=commission,
            )

    def _get_closed_position_info(self, ticket: int) -> dict[str, float | str]:
        """Kapalı pozisyonun history deal kayıtlarını okuyup kapanış bilgisini döndürür."""
        date_to = datetime.now(timezone.utc)
        date_from = date_to - pd.Timedelta(days=30)

        # Önce doğrudan position bazlı sorgu dene (en güvenilir yol).
        pos_deals = []
        try:
            direct_deals = mt5.history_deals_get(position=ticket)
            if direct_deals:
                pos_deals = list(direct_deals)
        except TypeError:
            pos_deals = []

        # Fallback: tarih aralığında manuel filtreleme.
        if not pos_deals:
            deals = mt5.history_deals_get(date_from, date_to) or []
            pos_deals = [
                d
                for d in deals
                if int(getattr(d, "position_id", 0)) == ticket or int(getattr(d, "order", 0)) == ticket
            ]

        deal_entry_out = int(getattr(mt5, "DEAL_ENTRY_OUT", 1))
        out_deals = [d for d in pos_deals if int(getattr(d, "entry", -1)) == deal_entry_out]

        if not pos_deals:
            return {
                "reason_label": "UNKNOWN_CLOSE",
                "pnl": 0.0,
                "close_price": 0.0,
                "swap": 0.0,
                "commission": 0.0,
            }

        # Bazı broker/hesap türlerinde OUT flag beklenen gibi gelmeyebilir.
        if not out_deals:
            out_deals = pos_deals

        # Son çıkış deal'i kapanış kaydı olarak kabul edilir.
        deal = sorted(out_deals, key=lambda d: int(getattr(d, "time_msc", getattr(d, "time", 0))))[-1]
        reason = int(getattr(deal, "reason", -1))
        reason_label = self._deal_reason_label(reason)

        return {
            "reason_label": f"{reason_label}",
            "pnl": float(getattr(deal, "profit", 0.0)),
            "close_price": float(getattr(deal, "price", 0.0)),
            "swap": float(getattr(deal, "swap", 0.0)),
            "commission": float(getattr(deal, "commission", 0.0)),
        }

    def _manage_open_positions(self) -> None:
        """Açık pozisyonlarda BE ve partial TP kurallarını uygular."""
        positions = mt5.positions_get(symbol=self.symbol) or []
        if not positions:
            return

        for pos in positions:
            ticket = int(pos.ticket)
            meta = self._tracked_positions.get(ticket)
            if not meta:
                continue

            rr_now = self._current_rr(pos, meta)
            if rr_now is None:
                continue

            # 1R'de SL break-even'a çek.
            if self.enable_break_even and (not bool(meta.get("be_done", False))) and rr_now >= self.break_even_rr:
                if self._move_sl_to_break_even(pos, meta):
                    meta["be_done"] = True

            # 1.5R'de kısmi kar al.
            if self.enable_partial_tp and (not bool(meta.get("partial_done", False))) and rr_now >= self.partial_tp_rr:
                if self._partial_close(pos, meta):
                    meta["partial_done"] = True

    def _current_rr(self, pos: Any, meta: dict[str, Any]) -> float | None:
        """Anlık RR değerini hesaplar."""
        entry = float(meta.get("entry_price", 0.0))
        initial_sl = float(meta.get("initial_sl", 0.0))
        if entry <= 0 or initial_sl <= 0:
            return None

        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return None

        side = str(meta.get("side", "")).upper()
        if side == "BUY":
            risk = entry - initial_sl
            reward = float(tick.bid) - entry
        else:
            risk = initial_sl - entry
            reward = entry - float(tick.ask)

        if risk <= 0:
            return None
        return reward / risk

    def _move_sl_to_break_even(self, pos: Any, meta: dict[str, Any]) -> bool:
        """SL'i giriş fiyatına taşır."""
        entry = float(meta.get("entry_price", 0.0))
        current_sl = float(getattr(pos, "sl", 0.0))
        side = str(meta.get("side", "")).upper()

        if side == "BUY" and current_sl >= entry:
            return False
        if side == "SELL" and current_sl <= entry and current_sl > 0:
            return False

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self.symbol,
            "position": int(pos.ticket),
            "sl": entry,
            "tp": float(getattr(pos, "tp", 0.0)),
            "magic": int(getattr(pos, "magic", 0)),
        }

        result = mt5.order_send(request)
        if result is None:
            self.logger.warning("BE SL güncellemesi başarısız | Ticket=%d | Hata=%s", int(pos.ticket), mt5.last_error())
            return False

        ok = int(getattr(result, "retcode", 0)) in {
            int(getattr(mt5, "TRADE_RETCODE_DONE", -1)),
            int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", -2)),
        }
        if not ok:
            self.logger.warning(
                "BE SL güncellemesi reddedildi | Ticket=%d | Kod=%d | %s",
                int(pos.ticket),
                int(getattr(result, "retcode", 0)),
                str(getattr(result, "comment", "")),
            )
            return False

        self.logger.info("BE AKTİF | Ticket=%d | SL -> %.5f", int(pos.ticket), entry)
        self._append_audit_event(
            event_type="MOVE_TO_BE",
            tf=str(meta.get("tf", "UNK")),
            side=str(meta.get("side", "UNK")),
            ticket=int(pos.ticket),
            reason=f"Reached RR >= {self.break_even_rr}",
            entry_price=entry,
            close_price=0.0,
            pnl=0.0,
            volume=float(getattr(pos, "volume", 0.0)),
        )
        return True

    def _partial_close(self, pos: Any, meta: dict[str, Any]) -> bool:
        """Pozisyonun belirlenen oranını kapatır."""
        side = str(meta.get("side", "")).upper()
        tick = mt5.symbol_info_tick(self.symbol)
        info = mt5.symbol_info(self.symbol)
        if tick is None or info is None:
            return False

        current_volume = float(getattr(pos, "volume", 0.0))
        target_close = self._normalize_volume(current_volume * self.partial_close_ratio, info)
        if target_close <= 0:
            return False

        min_volume = float(getattr(info, "volume_min", 0.01))
        remaining = current_volume - target_close
        if remaining < min_volume:
            target_close = self._normalize_volume(current_volume - min_volume, info)
            if target_close <= 0:
                return False

        close_type = mt5.ORDER_TYPE_SELL if side == "BUY" else mt5.ORDER_TYPE_BUY
        close_price = float(tick.bid) if side == "BUY" else float(tick.ask)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "position": int(pos.ticket),
            "volume": float(target_close),
            "type": int(close_type),
            "price": close_price,
            "deviation": self.slippage,
            "magic": int(getattr(pos, "magic", 0)),
            "comment": "SMC-PARTIAL",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None:
            self.logger.warning("Partial close başarısız | Ticket=%d | Hata=%s", int(pos.ticket), mt5.last_error())
            return False

        ok = int(getattr(result, "retcode", 0)) in {
            int(getattr(mt5, "TRADE_RETCODE_DONE", -1)),
            int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", -2)),
        }
        if not ok:
            self.logger.warning(
                "Partial close reddedildi | Ticket=%d | Kod=%d | %s",
                int(pos.ticket),
                int(getattr(result, "retcode", 0)),
                str(getattr(result, "comment", "")),
            )
            return False

        self.logger.info(
            "PARTIAL CLOSE | Ticket=%d | KapananLot=%.2f | KalanLot~%.2f",
            int(pos.ticket),
            float(target_close),
            max(current_volume - float(target_close), 0.0),
        )
        self._append_audit_event(
            event_type="PARTIAL_CLOSE",
            tf=str(meta.get("tf", "UNK")),
            side=side,
            ticket=int(pos.ticket),
            reason=f"Reached RR >= {self.partial_tp_rr}",
            entry_price=float(meta.get("entry_price", 0.0)),
            close_price=close_price,
            pnl=0.0,
            volume=float(target_close),
        )
        return True

    @staticmethod
    def _normalize_volume(raw_volume: float, symbol_info: Any) -> float:
        """Lot'u sembolün volume_step yapısına uydurur."""
        step = float(getattr(symbol_info, "volume_step", 0.01))
        min_vol = float(getattr(symbol_info, "volume_min", 0.01))
        if raw_volume < min_vol:
            return 0.0
        units = int(raw_volume / step)
        norm = units * step
        return round(norm, 2)

    def _tf_from_magic(self, magic: int) -> str:
        for tf, mg in MAGIC_NUMBERS.items():
            if mg == magic:
                return tf
        return "UNK"

    @staticmethod
    def _deal_reason_label(reason: int) -> str:
        mapping = {
            int(getattr(mt5, "DEAL_REASON_CLIENT", -100)): "MANUAL_CLIENT",
            int(getattr(mt5, "DEAL_REASON_EXPERT", -101)): "BOT_EXPERT",
            int(getattr(mt5, "DEAL_REASON_SL", -102)): "STOP_LOSS",
            int(getattr(mt5, "DEAL_REASON_TP", -103)): "TAKE_PROFIT",
            int(getattr(mt5, "DEAL_REASON_SO", -104)): "STOP_OUT",
        }
        return mapping.get(reason, f"REASON_{reason}")
