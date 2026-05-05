from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SwingPoint:
    """Piyasa yapısı analizi için swing noktası taşıyıcısı."""

    index: int
    time: datetime
    price: float
    kind: str  # "high" veya "low"


@dataclass
class LiquiditySweepSignal:
    """Yönlü (bullish/bearish) likidite süpürme sinyali bilgisi."""

    index: int
    time: datetime
    direction: str
    swept_swing_index: int
    swept_level: float
    wick_price: float
    close_price: float
    sweep_distance_points: float


@dataclass
class BOSSignal:
    """Yönlü BOS sinyali (close ile kırılım zorunlu)."""

    index: int
    time: datetime
    direction: str
    broken_swing_index: int
    broken_level: float
    close_price: float
    body_size_points: float


@dataclass
class FVGZone:
    """ICT yönlü FVG zonu."""

    id: str
    direction: str
    created_index: int
    created_time: datetime
    lower: float
    upper: float
    size_points: float
    active: bool = True
    mitigated_index: Optional[int] = None
    mitigated_time: Optional[datetime] = None


@dataclass
class Trade:
    """Backtest sırasında açık/kapalı pozisyon verisi."""

    id: str
    symbol: str
    timeframe: str
    side: str
    open_index: int
    open_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    spread_points: float
    reason: str
    status: str = "open"
    close_index: Optional[int] = None
    close_time: Optional[datetime] = None
    close_price: Optional[float] = None
    close_reason: Optional[str] = None
    pnl_usd: float = 0.0
    rr_realized: float = 0.0
    commission_usd: float = 0.0
    swap_usd: float = 0.0
    nights_held: int = 0


@dataclass
class BacktestResult:
    """Tek timeframe için özet backtest sonucu."""

    timeframe: str
    initial_balance: float
    final_balance: float
    total_pnl: float
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    total_trades: int
    wins: int
    losses: int
    rr_avg: float
    equity_curve: list[float] = field(default_factory=list)
